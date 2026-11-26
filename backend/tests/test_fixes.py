"""Every fixer: it resolves its issue, keeps the graph valid, and re-verifies.
LLM fixers are tested on both paths: scripted LLM output and template fallback."""

import uuid

import pytest
from sqlalchemy import select

from app.llm.breaker import MemoryBreaker
from app.llm.providers.base import ProviderUnavailable
from app.models import Blueprint, Edge, Issue, Node, Project, QualityReport
from app.models.enums import EdgeType, NodeType
from app.services import graph
from app.services.fixes import FixNotPossible, apply_fix, normalise_path, regenerate_subgraph
from app.services.verification import run_verification
from app.verify.rules import path_problems
from tests.llm_fakes import FOOD_BRIEF, ScriptedProvider

T, E = NodeType, EdgeType
AC = ["Given a customer, when they pay, then the order is confirmed"]


@pytest.fixture
def bp(db):
    project = Project(name="F")
    db.add(project)
    db.flush()
    b = Blueprint(project_id=project.id, title="F", brief=FOOD_BRIEF)
    db.add(b)
    db.commit()
    return b


class Builder:
    def __init__(self, db, bp):
        self.db, self.bp = db, bp

    def node(self, t, title, **body):
        return graph.create_node(self.db, self.bp, node_type=t, title=title, body=body)

    def link(self, a, b, t):
        graph.create_edge(self.db, self.bp, src_id=a.id, dst_id=b.id, edge_type=t, body={})


@pytest.fixture
def g(db, bp):
    """A small, mostly-healthy blueprint to break in specific ways."""
    b = Builder(db, bp)
    b.req = b.node(
        T.requirement,
        "Customers order and pay for food online",
        kind="functional",
        nfr_category="none",
        description="Customers build a cart and pay by card.",
    )
    b.story = b.node(
        T.story,
        "As a customer, I want to pay for my order so that it is placed",
        acceptance_criteria=AC,
    )
    b.mod = b.node(T.module, "Ordering", responsibility="Carts, orders and payments")
    b.ent = b.node(
        T.entity,
        "Order",
        fields=[{"name": "id", "type": "uuid", "primary_key": True, "nullable": False}],
    )
    b.api = b.node(T.api, "POST /orders", method="POST", path="/orders", summary="Place order")
    b.test = b.node(T.test, "Customer pays and order is placed", kind="e2e", steps=["pay"])
    b.link(b.req, b.story, E.refines)
    b.link(b.story, b.mod, E.implemented_by)
    b.link(b.mod, b.api, E.exposes)
    b.link(b.api, b.ent, E.persists)
    b.link(b.story, b.test, E.verified_by)
    return b


def issues(db, bp, code=None):
    qr = db.scalar(
        select(QualityReport)
        .where(QualityReport.blueprint_id == bp.id)
        .order_by(QualityReport.created_at.desc())
    )
    return [i for i in qr.issues if code is None or i.rule_code == code]


def fix(db, bp, code, *, providers=None, which=0):
    run_verification(db, bp)
    target = issues(db, bp, code)
    assert target, f"expected a {code} issue"
    return apply_fix(db, target[which], providers=providers or [], breaker=MemoryBreaker())


def nodes_of(db, bp, t):
    return list(
        db.scalars(
            select(Node).where(Node.blueprint_id == bp.id, Node.type == t).order_by(Node.position)
        )
    )


# ------------------------------------------------------------------ generative (fallback)


def test_tr001_fallback_adds_story_test_and_links(db, bp, g):
    orphan_req = g.node(T.requirement, "Riders see the delivery address", kind="functional")
    out = fix(db, bp, "TR-001")
    assert out["provider"] == "demo" and out["score_after"] >= 0
    story = db.scalar(select(Edge).where(Edge.src_id == orphan_req.id, Edge.type == E.refines))
    assert story is not None
    s = db.get(Node, story.dst_id)
    assert s.body["acceptance_criteria"] and s.type == T.story
    assert db.scalar(select(Edge).where(Edge.src_id == s.id, Edge.type == E.verified_by))
    assert db.scalar(select(Edge).where(Edge.src_id == s.id, Edge.type == E.implemented_by))
    assert not [i for i in issues(db, bp, "TR-001") if orphan_req.id in i.node_ids]


def test_tr001_with_llm_output(db, bp, g):
    g.node(T.requirement, "Riders see the delivery address", kind="functional")
    llm = ScriptedProvider(
        "gemini",
        [
            {
                "stories": [
                    {
                        "title": "As a rider, I want to see the drop-off address "
                        "so that I deliver on time",
                        "acceptance_criteria": [
                            "Given an accepted order, when I open it, then I see the address",
                            "Given no GPS, when I open it, then I still see the text",
                        ],
                        "test": {
                            "title": "Rider sees address",
                            "kind": "e2e",
                            "steps": ["Accept", "Open"],
                        },
                    }
                ]
            }
        ],
    )
    out = fix(db, bp, "TR-001", providers=[llm])
    assert out["provider"] == "gemini" and llm.requests[0].stage == "fix"
    assert "Riders see the delivery address" in llm.requests[0].prompt
    titles = [n.title for n in nodes_of(db, bp, T.story)]
    assert any("drop-off address" in t for t in titles)


def test_llm_down_falls_back_to_template(db, bp, g):
    g.node(T.story, "As a rider, I want to go online so that I get offers", acceptance_criteria=AC)
    llm = ScriptedProvider("gemini", [ProviderUnavailable("quota", retry_after=999)])
    out = fix(db, bp, "TR-002", providers=[llm])
    assert out["provider"] == "demo" and len(llm.requests) == 1


def test_tr002_cp001_cp003_cp004_fallbacks(db, bp, g):
    s = g.node(
        T.story,
        "As a rider, I want to go online so that I get offers",
        acceptance_criteria=["works"],
    )
    g.link(s, g.mod, E.implemented_by)
    g.link(g.req, s, E.refines)
    fix(db, bp, "TR-002")
    assert db.scalar(select(Edge).where(Edge.src_id == s.id, Edge.type == E.verified_by))

    out = fix(db, bp, "CP-001")
    db.refresh(s)
    assert all(c.lower().startswith("given") for c in s.body["acceptance_criteria"])
    assert out["changed"] == [s.key]

    before = len(nodes_of(db, bp, T.requirement))
    fix(db, bp, "CP-003")  # missing performance/security/availability NFRs
    assert len(nodes_of(db, bp, T.requirement)) == before + 1

    risk = g.node(T.risk, "Card fraud", likelihood="high", impact="high", mitigation="")
    fix(db, bp, "CP-004")
    db.refresh(risk)
    assert len(risk.body["mitigation"]) >= 15
    assert db.scalar(select(Edge).where(Edge.src_id == risk.id, Edge.type == E.threatens))


# ------------------------------------------------------------------ deterministic


def test_tr003_links_api_to_module_and_entity_by_path(db, bp, g):
    api = g.node(T.api, "GET /orders/{id}", method="GET", path="/orders/{id}", summary="One")
    out = fix(db, bp, "TR-003")
    assert "module" in out["action"] and "entity" in out["action"]
    persists = db.scalar(select(Edge).where(Edge.src_id == api.id, Edge.type == E.persists))
    assert persists.dst_id == g.ent.id  # matched "/orders" -> Order, not by embedding guess
    assert db.scalar(select(Edge).where(Edge.dst_id == api.id, Edge.type == E.exposes))


def test_tr004_orphan_story_linked_to_most_similar_requirement(db, bp, g):
    other = g.node(T.requirement, "Restaurants manage their menu", kind="functional")
    g.link(other, g.node(T.story, "As an owner I edit dishes", acceptance_criteria=AC), E.refines)
    orphan = g.node(
        T.story,
        "As a customer, I want to pay by card so the order is placed",
        acceptance_criteria=AC,
    )
    run_verification(db, bp)
    target = next(i for i in issues(db, bp, "TR-004") if orphan.id in i.node_ids)
    apply_fix(db, target, providers=[], breaker=MemoryBreaker())
    edge = db.scalar(select(Edge).where(Edge.dst_id == orphan.id, Edge.type == E.refines))
    assert edge.src_id == g.req.id  # the payment requirement, not the menu one


def test_tr005_module_linked_to_story(db, bp, g):
    mod = g.node(T.module, "Payments", responsibility="Card payments")
    g.link(mod, g.api, E.exposes)
    fix(db, bp, "TR-005")
    assert db.scalar(select(Edge).where(Edge.dst_id == mod.id, Edge.type == E.implemented_by))


def test_cp002_adds_missing_crud_endpoints(db, bp, g):
    out = fix(db, bp, "CP-002")
    paths = sorted(n.title for n in nodes_of(db, bp, T.api))
    assert paths == [
        "DELETE /orders/{id}",
        "GET /orders/{id}",
        "PATCH /orders/{id}",
        "POST /orders",
    ]
    assert "Added" in out["action"]
    for api in nodes_of(db, bp, T.api):
        assert db.scalar(select(Edge).where(Edge.dst_id == api.id, Edge.type == E.exposes))
    assert not issues(db, bp, "CP-002")


@pytest.mark.parametrize(
    ("bad", "good"),
    [
        ("/getOrders", "/orders"),
        ("/v1/Order_Items/{itemId}", "/order-items/{item_id}"),
        ("/orders/create", "/orders"),
        ("/deleteUser/{id}", "/user/{id}"),
    ],
)
def test_normalise_path(bad, good):
    assert normalise_path(bad) == good
    assert path_problems(good) == []


def test_cv001_and_cv002_rename(db, bp, g):
    api = g.node(T.api, "GET /getOrders", method="GET", path="/getOrders", summary="List")
    g.link(g.mod, api, E.exposes)
    g.link(api, g.ent, E.persists)
    fix(db, bp, "CV-001")
    db.refresh(api)
    assert api.body["path"] == "/orders" and api.title == "GET /orders"

    ent = g.node(
        T.entity,
        "payments",
        fields=[{"name": "paidAt", "type": "timestamp", "primary_key": False, "nullable": False}],
    )
    g.link(g.api, ent, E.persists)
    fix(db, bp, "CV-002")
    db.refresh(ent)
    assert ent.title == "Payment"
    names = [f["name"] for f in ent.body["fields"]]
    assert names == ["id", "paid_at"] and ent.body["fields"][0]["primary_key"]


def test_cv001_unfixable_path_reports_not_possible(db, bp, g):
    api = g.node(T.api, "GET /{id}", method="GET", path="/{Id}", summary="x")
    g.link(g.mod, api, E.exposes)
    g.link(api, g.ent, E.persists)
    run_verification(db, bp)
    issue = next(i for i in issues(db, bp, "CV-001") if api.id in i.node_ids)
    issue.details = {**issue.details}
    api.body = {**api.body, "path": "/{id}"}  # already as clean as it can get
    db.commit()
    with pytest.raises(FixNotPossible):
        apply_fix(db, issue, providers=[], breaker=MemoryBreaker())


def test_duplicate_merge_moves_links_and_deletes(db, bp, g):
    dup = g.node(
        T.requirement, g.req.title + ".", kind="functional", description=g.req.body["description"]
    )
    extra = g.node(
        T.story, "As a customer, I want a receipt so that I can expense it", acceptance_criteria=AC
    )
    g.link(dup, extra, E.refines)
    g.link(dup, g.story, E.refines)  # same link as the keeper already has
    out = fix(db, bp, "DUP-001")
    assert db.get(Node, dup.id) is None
    refines = {
        e.dst_id
        for e in db.scalars(select(Edge).where(Edge.src_id == g.req.id, Edge.type == E.refines))
    }
    assert refines == {g.story.id, extra.id}
    assert "1 links moved" in out["action"]  # the duplicate edge was dropped, not copied


def test_contradiction_needs_llm_or_human(db, bp, g):
    a = g.node(
        T.requirement,
        "Data encryption",
        kind="non_functional",
        nfr_category="security",
        description="All customer data must be encrypted at rest.",
    )
    b = g.node(
        T.requirement,
        "Fast analytics",
        kind="non_functional",
        nfr_category="performance",
        description="Customer data is stored unencrypted to speed up analytics.",
    )
    s = g.node(T.story, "As an analyst I query data fast", acceptance_criteria=AC)
    g.link(b, s, E.refines)
    run_verification(db, bp)
    (con,) = issues(db, bp, "CON-001")
    with pytest.raises(FixNotPossible):
        apply_fix(db, con, providers=[], breaker=MemoryBreaker())

    llm = ScriptedProvider(
        "groq",
        [
            {
                "title": "Fast analytics on encrypted data",
                "description": "Analytics run on an encrypted replica "
                "with column-level decryption.",
                "rationale": "Keeps encryption at rest.",
            }
        ],
    )
    out = apply_fix(db, con, providers=[llm], breaker=MemoryBreaker())
    db.refresh(b)
    db.refresh(s)
    assert b.title == "Fast analytics on encrypted data" and out["provider"] == "groq"
    assert s.stale is True  # editing b propagated impact to its story
    assert not issues(db, bp, "CON-001")
    assert a.id  # untouched


def test_fix_of_deleted_nodes_is_reported(db, bp, g):
    orphan = g.node(T.module, "Ghost")
    run_verification(db, bp)
    issue = next(i for i in issues(db, bp, "TR-004") if orphan.id in i.node_ids)
    graph.delete_node(db, orphan)
    with pytest.raises(FixNotPossible):
        apply_fix(db, issue, providers=[], breaker=MemoryBreaker())


def test_unknown_rule_not_fixable(db, bp, g):
    run_verification(db, bp)
    qr = db.scalar(select(QualityReport).where(QualityReport.blueprint_id == bp.id))
    fake = Issue(
        report_id=qr.id,
        rule_code="ZZ-999",
        category=issues(db, bp)[0].category,
        severity=issues(db, bp)[0].severity,
        message="x",
        node_ids=[],
        fix_hint="",
    )
    db.add(fake)
    db.commit()
    with pytest.raises(FixNotPossible):
        apply_fix(db, fake, providers=[], breaker=MemoryBreaker())


# ------------------------------------------------------------------ regenerate subgraph


def test_regenerate_subgraph_with_llm_preserves_ids_and_status(db, bp, g):
    from app.models.enums import NodeStatus

    graph.set_status(db, g.story, NodeStatus.in_progress)
    graph.update_node(
        db, g.req, user_id=None, title="Customers order, pay and tip online", body=None
    )
    db.refresh(g.story)
    assert g.story.stale
    llm = ScriptedProvider(
        "gemini",
        [
            {
                "updates": [
                    {
                        "key": g.story.key,
                        "title": "As a customer, I want to pay and add a tip so that riders "
                        "are rewarded",
                        "description": "",
                        "acceptance_criteria": [
                            "Given checkout, when I add a tip, then it is added to the total"
                        ],
                        "steps": [],
                    },
                    {
                        "key": "NOT-A-KEY",
                        "title": "ignored",
                        "description": "",
                        "acceptance_criteria": [],
                        "steps": [],
                    },
                ]
            }
        ],
    )
    out = regenerate_subgraph(db, bp, g.req.id, providers=[llm], breaker=MemoryBreaker())
    db.refresh(g.story)
    assert out["updated"] == [g.story.key] and out["provider"] == "gemini"
    assert "tip" in g.story.title and g.story.status == NodeStatus.in_progress
    assert not g.story.stale and g.story.body["acceptance_criteria"][0].startswith("Given")
    assert db.scalar(select(Node).where(Node.blueprint_id == bp.id, Node.stale.is_(True))) is None
    prompt = llm.requests[0].prompt
    assert "tip" in prompt and g.story.key in prompt


def test_regenerate_subgraph_demo_mode_acknowledges(db, bp, g):
    graph.update_node(db, g.req, user_id=None, title="Customers order and pay", body=None)
    out = regenerate_subgraph(db, bp, g.req.id, providers=[], breaker=MemoryBreaker())
    assert out["provider"] == "demo" and out["updated"] == []
    assert set(out["reviewed"]) >= {g.story.key, g.mod.key}
    assert db.scalar(select(Node).where(Node.blueprint_id == bp.id, Node.stale.is_(True))) is None


def test_regenerate_nothing_stale_and_bad_root(db, bp, g):
    assert regenerate_subgraph(db, bp, g.req.id, providers=[])["message"] == "Nothing is stale"
    with pytest.raises(FixNotPossible):
        regenerate_subgraph(db, bp, uuid.uuid4(), providers=[])


# ------------------------------------------------------------------ via Celery task


def test_fix_task_end_to_end(db, bp, g, monkeypatch):
    from sqlalchemy.orm import Session

    from app.models import Job, User
    from app.models.enums import JobKind, JobStatus
    from app.services import fixes
    from app.worker import tasks

    conn = db.connection()
    monkeypatch.setattr(
        tasks,
        "session_factory",
        lambda: Session(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        ),
    )
    monkeypatch.setattr(fixes, "default_providers", lambda: [])
    monkeypatch.setattr(fixes, "RedisBreaker", MemoryBreaker)
    g.node(T.module, "Lonely")
    run_verification(db, bp)
    issue = next(i for i in issues(db, bp, "TR-004"))
    user = User(email="f@example.com", display_name="F", password_hash="x")
    db.add(user)
    db.flush()
    job = Job(
        blueprint_id=bp.id,
        user_id=user.id,
        kind=JobKind.fix_issue,
        params={"issue_id": str(issue.id)},
    )
    db.add(job)
    db.commit()
    tasks.fix_issue.apply(args=[str(job.id)])
    db.refresh(job)
    assert job.status == JobStatus.succeeded, job.error
    assert job.result["score_after"] is not None and job.result["action"].startswith("Linked")

    # a fix that can't be done fails cleanly with a user-facing code
    job2 = Job(
        blueprint_id=bp.id,
        user_id=user.id,
        kind=JobKind.fix_issue,
        params={"issue_id": str(uuid.uuid4())},
    )
    db.add(job2)
    db.commit()
    tasks.fix_issue.apply(args=[str(job2.id)])
    db.refresh(job2)
    assert job2.status == JobStatus.failed and job2.error["code"] == "ISSUE_GONE"

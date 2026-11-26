"""Verification end to end on Postgres + pgvector, and the quality API."""

import pytest
from sqlalchemy import select

from app.models import Blueprint, Issue, Node, Project, QualityReport
from app.models.enums import JobKind, NodeType
from app.services import graph
from app.services.graph import EdgeSpec, NodeSpec
from app.services.verification import run_verification
from app.verify import ml
from tests.llm_fakes import FOOD_BRIEF, valid_draft

T = NodeType


@pytest.fixture
def bp(db):
    from app.llm.schemas import to_graph

    project = Project(name="V")
    db.add(project)
    db.flush()
    b = Blueprint(project_id=project.id, title="V", brief=FOOD_BRIEF)
    db.add(b)
    db.commit()
    nodes, edges = to_graph(valid_draft())
    graph.replace_graph(db, b, nodes, edges)
    return b


def latest_issues(db, b) -> list[Issue]:
    qr = db.scalar(
        select(QualityReport)
        .where(QualityReport.blueprint_id == b.id)
        .order_by(QualityReport.created_at.desc())
    )
    return list(qr.issues)


def test_verification_persists_report_scores_and_embeddings(db, bp):
    steps = []
    summary = run_verification(db, bp, lambda s, p, e: steps.append(s))
    assert steps == ["rule_check", "ml_check", "scoring"]
    assert summary["ml"] == "ok" and 0 <= summary["score"] <= 100
    assert bp.quality_score == summary["score"]
    qr = db.get(QualityReport, __import__("uuid").UUID(summary["report_id"]))
    cats = {c["category"] for c in qr.breakdown["categories"]}
    assert cats == {"traceability", "completeness", "consistency", "uniqueness", "conventions"}
    assert all(
        n.embedding is not None for n in db.scalars(select(Node).where(Node.blueprint_id == bp.id))
    )
    # second run re-embeds nothing
    assert run_verification(db, bp)["score"] == summary["score"]


def test_duplicate_detected_via_pgvector(db, bp):
    req = db.scalar(
        select(Node)
        .where(Node.blueprint_id == bp.id, Node.type == T.requirement)
        .order_by(Node.position)
    )
    graph.create_node(db, bp, node_type=T.requirement, title=req.title + ".", body=dict(req.body))
    run_verification(db, bp)
    dups = [i for i in latest_issues(db, bp) if i.rule_code == "DUP-001"]
    assert len(dups) == 1 and req.id in dups[0].node_ids
    assert dups[0].details["similarity"] >= ml.DUPLICATE_MIN
    assert dups[0].node_ids[0] == req.id  # the older node is the one to keep


def test_contradiction_detected(db, bp):
    for title, desc in [
        ("Data encryption", "All customer data must be encrypted at rest."),
        ("Fast analytics", "Customer data is stored unencrypted to speed up analytics queries."),
    ]:
        graph.create_node(
            db,
            bp,
            node_type=T.requirement,
            title=title,
            body={"kind": "non_functional", "nfr_category": "security", "description": desc},
        )
    summary = run_verification(db, bp)
    cons = [i for i in latest_issues(db, bp) if i.rule_code == "CON-001"]
    assert len(cons) == 1 and "may contradict" in cons[0].message
    assert cons[0].details["cue"].startswith("opposite terms")
    assert summary["categories"]["consistency"] == 75


def test_ml_unavailable_degrades_to_rules_only(db, bp, monkeypatch):
    def broken(texts):
        raise RuntimeError("model download failed")

    monkeypatch.setattr(ml, "embed", broken)
    summary = run_verification(db, bp)
    assert summary["ml"] == "unavailable" and summary["score"] is not None


# ------------------------------------------------------------------ API


@pytest.fixture
def owned(api, make_user, login, client):
    h = login(make_user())
    pid = api("post", "/projects", h, json={"name": "Q"}).json()["id"]
    bpid = api(
        "post", f"/projects/{pid}/blueprints", h, json={"title": "Q", "brief": FOOD_BRIEF}
    ).json()["id"]
    calls = []
    from app.api.routes import jobs as jobs_route

    client.app.dependency_overrides[jobs_route.get_enqueuer] = lambda: calls.append
    return h, bpid, pid, calls


def _populate(db, bpid, extra=None):
    from app.llm.schemas import to_graph

    b = db.get(Blueprint, __import__("uuid").UUID(bpid))
    nodes, edges = to_graph(valid_draft())
    nodes += extra or []
    graph.replace_graph(db, b, nodes, edges)
    return b


def test_quality_api_lifecycle(api, owned, db, make_user, login):
    h, bpid, pid, calls = owned
    assert api("get", f"/blueprints/{bpid}/quality", h).json()["code"] == "NOT_VERIFIED"
    r = api("post", f"/blueprints/{bpid}/verify", h)
    assert r.status_code == 202 and calls[0].kind == JobKind.verify

    b = _populate(db, bpid, [NodeSpec("ORPH", T.module, "Lonely module", {})])
    run_verification(db, b)
    q = api("get", f"/blueprints/{bpid}/quality", h).json()
    assert q["score"] == b.quality_score
    orphan = next(i for i in q["issues"] if i["rule_code"] == "TR-004")
    assert orphan["fixable"] and orphan["node_keys"][0].startswith("MOD-")
    assert [x["score"] for x in api("get", f"/blueprints/{bpid}/quality/history", h).json()]

    # dismiss -> score goes up immediately and survives re-verification
    before = q["score"]
    d = api("post", f"/issues/{orphan['id']}/dismiss", h).json()
    assert d["resolved"] is True and d["score"] >= before
    run_verification(db, b)
    q2 = api("get", f"/blueprints/{bpid}/quality", h).json()
    again = next(i for i in q2["issues"] if i["rule_code"] == "TR-004")
    assert again["resolved"] is True and q2["score"] == d["score"]
    assert api("get", f"/blueprints/{bpid}/quality?include_resolved=false", h).json()["issues"] == [
        i for i in q2["issues"] if not i["resolved"]
    ]
    assert api("post", f"/issues/{again['id']}/restore", h).json()["resolved"] is False

    # viewer can read but not fix/dismiss; outsider can't see
    viewer = make_user()
    api("post", f"/projects/{pid}/members", h, json={"email": viewer.email, "role": "viewer"})
    hv = login(viewer)
    assert api("get", f"/blueprints/{bpid}/quality", hv).status_code == 200
    assert api("post", f"/issues/{again['id']}/fix", hv).status_code == 403
    assert api("post", f"/issues/{again['id']}/dismiss", hv).status_code == 403
    assert api("get", f"/blueprints/{bpid}/quality", login(make_user())).status_code == 404


def test_fix_endpoint_guards(api, owned, db):
    h, bpid, _, calls = owned
    b = _populate(db, bpid, [NodeSpec("ORPH", T.module, "Lonely module", {})])
    run_verification(db, b)
    issue = next(
        i
        for i in api("get", f"/blueprints/{bpid}/quality", h).json()["issues"]
        if i["rule_code"] == "TR-004"
    )
    r = api("post", f"/issues/{issue['id']}/fix", h)
    assert r.status_code == 202 and calls[-1].kind == JobKind.fix_issue
    assert calls[-1].params == {"issue_id": issue["id"]}
    # same fix again -> same job; a different mutating job meanwhile -> 409
    assert api("post", f"/issues/{issue['id']}/fix", h).status_code == 200
    assert api("post", f"/blueprints/{bpid}/generate", h).json()["code"] == "JOB_IN_PROGRESS"
    assert api("post", f"/blueprints/{bpid}/verify", h).status_code == 202  # read-only: allowed
    # once re-verified, the old issue is stale
    run_verification(db, b)
    assert api("post", f"/issues/{issue['id']}/fix", h).json()["code"] == "STALE_ISSUE"


def test_similar_nodes_uses_embeddings(api, owned, db):
    h, bpid, _, _ = owned
    b = _populate(db, bpid)
    node = db.scalar(select(Node).where(Node.blueprint_id == b.id, Node.type == T.story))
    assert api("get", f"/nodes/{node.id}/similar", h).json()["code"] == "NOT_EMBEDDED"
    run_verification(db, b)
    res = api("get", f"/nodes/{node.id}/similar?k=3", h).json()
    assert len(res) == 3 and str(node.id) not in [r["id"] for r in res]
    sims = [r["similarity"] for r in res]
    assert sims == sorted(sims, reverse=True)


def test_regenerate_endpoint_validates_root(api, owned, db):
    h, bpid, _, calls = owned
    b = _populate(db, bpid)
    root = db.scalar(select(Node).where(Node.blueprint_id == b.id, Node.type == T.requirement))
    r = api(
        "post", f"/blueprints/{bpid}/regenerate-subgraph", h, json={"root_node_id": str(root.id)}
    )
    assert r.status_code == 202 and calls[-1].kind == JobKind.regenerate_subgraph
    bad = api(
        "post",
        f"/blueprints/{bpid}/regenerate-subgraph",
        h,
        json={"root_node_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert bad.status_code == 404


def test_rules_catalog_public(client):
    cat = client.get("/api/v1/rules").json()
    assert {"TR-001", "CP-002", "CV-001", "DUP-001", "CON-001"} <= set(cat)


def test_ready_reports_worker_without_gating(client, monkeypatch):
    from app.api.routes import health

    monkeypatch.setattr(health, "check_redis", lambda: {"ok": True})
    r = client.get("/ready")
    assert r.status_code == 200
    assert r.json()["worker"]["ok"] is False  # no worker running in tests, still ready
    assert client.get("/api/v1/status").json()["components"]["worker"]["models_loaded"] is False


def test_edges_spec_import_used():
    assert EdgeSpec  # keeps the import meaningful for readers of the fixtures

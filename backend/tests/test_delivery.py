"""Progress roll-ups, exports (md/json/pdf), samples and the sandbox reset."""

import pytest
from sqlalchemy import select

from app.models import Blueprint, Node, Project
from app.models.enums import NodeStatus, NodeType
from app.services import graph, samples
from app.services.progress import rollups
from app.services.verification import run_verification
from tests.llm_fakes import FOOD_BRIEF


@pytest.fixture
def owned(api, make_user, login):
    h = login(make_user())
    pid = api("post", "/projects", h, json={"name": "D"}).json()["id"]
    r = api("post", f"/projects/{pid}/samples/food-delivery", h)
    assert r.status_code == 201, r.text
    return h, r.json()["id"], pid


def test_samples_listed_publicly(client):
    items = client.get("/api/v1/samples").json()
    assert {s["slug"] for s in items} == {
        "food-delivery",
        "hospital-appointments",
        "college-erp",
        "fintech-wallet",
    }
    assert all(s["nodes"] > 30 and s["generated_by"] for s in items)


def test_add_sample_copies_graph(api, owned):
    h, bp, _ = owned
    meta = api("get", f"/blueprints/{bp}", h).json()
    assert meta["is_sample"] and meta["status"] == "ready" and meta["provider"].startswith("sample")
    g = api("get", f"/blueprints/{bp}/graph", h).json()
    assert len(g["nodes"]) > 30 and len(g["edges"]) > 50


def test_unknown_sample_404(api, owned):
    h, _, pid = owned
    assert api("post", f"/projects/{pid}/samples/nope", h).status_code == 404


def test_progress_rollups(api, owned, db):
    h, bp, _ = owned
    p = api("get", f"/blueprints/{bp}/progress", h).json()
    assert p["overall"]["done"] == 0 and p["overall"]["total"] > 0
    first_req = p["requirements"][0]
    assert first_req["total"] > 0 and first_req["percent"] == 0
    # finish every story + test under the first requirement
    stories = [
        e["dst_id"]
        for e in api("get", f"/blueprints/{bp}/graph", h).json()["edges"]
        if e["src_id"] == first_req["id"] and e["type"] == "refines"
    ]
    graph_json = api("get", f"/blueprints/{bp}/graph", h).json()
    tests = [
        e["dst_id"]
        for e in graph_json["edges"]
        if e["src_id"] in stories and e["type"] == "verified_by"
    ]
    for nid in stories + tests:
        assert api("patch", f"/nodes/{nid}/status", h, json={"status": "done"}).status_code == 200
    p2 = api("get", f"/blueprints/{bp}/progress", h).json()
    assert p2["requirements"][0]["percent"] == 100
    assert p2["overall"]["by_status"]["done"] == len(set(stories + tests))
    assert 0 < p2["overall"]["percent"] < 100


def test_rollup_counts_shared_tests_once(db):
    project = Project(name="R")
    db.add(project)
    db.flush()
    bp = Blueprint(project_id=project.id, title="R", brief=FOOD_BRIEF)
    db.add(bp)
    db.commit()
    T = NodeType
    req = graph.create_node(db, bp, node_type=T.requirement, title="r", body={})
    s1 = graph.create_node(db, bp, node_type=T.story, title="s1 story", body={})
    s2 = graph.create_node(db, bp, node_type=T.story, title="s2 story", body={})
    t = graph.create_node(db, bp, node_type=T.test, title="shared", body={})
    for s in (s1, s2):
        graph.create_edge(db, bp, src_id=req.id, dst_id=s.id, edge_type="refines", body={})
        graph.create_edge(db, bp, src_id=s.id, dst_id=t.id, edge_type="verified_by", body={})
    graph.set_status(db, t, NodeStatus.done)
    r = rollups(db, bp.id)["requirements"][0]
    assert r["total"] == 3 and r["done"] == 1 and r["percent"] == 33


@pytest.mark.parametrize(
    ("fmt", "ctype", "magic"),
    [
        ("md", "text/markdown", b"# Food delivery marketplace"),
        ("json", "application/json", b"{"),
        ("pdf", "application/pdf", b"%PDF"),
    ],
)
def test_exports(api, owned, db, fmt, ctype, magic):
    h, bp, _ = owned
    run_verification(db, db.get(Blueprint, __import__("uuid").UUID(bp)))
    r = api("get", f"/blueprints/{bp}/export?format={fmt}", h)
    assert r.status_code == 200 and r.headers["content-type"].startswith(ctype)
    assert r.content.startswith(magic)
    assert f'filename="food-delivery-marketplace.{fmt}"' in r.headers["content-disposition"]
    if fmt == "md":
        text = r.text
        for heading in (
            "## Requirements",
            "## REST API",
            "## Data model",
            "## Risk register",
            "## Open quality issues",
            "Quality Score:",
        ):
            assert heading in text
        assert "| REQ-001 |" in text
    if fmt == "json":
        body = r.json()
        assert body["quality"]["score"] is not None
        assert {e["type"] for e in body["edges"]} >= {"refines", "exposes", "verified_by"}
    if fmt == "pdf":
        assert len(r.content) > 5000


def test_export_rejects_unknown_format_and_outsiders(api, owned, make_user, login):
    h, bp, _ = owned
    assert api("get", f"/blueprints/{bp}/export?format=docx", h).status_code == 422
    assert api("get", f"/blueprints/{bp}/export", login(make_user())).status_code == 404


def test_reset_sandbox_restores_verified_samples(db):
    from app.services.auth_service import ensure_demo_user

    ensure_demo_user(db)
    sandbox = samples.sandbox_project(db)
    junk = Blueprint(project_id=sandbox.id, title="visitor junk", brief=FOOD_BRIEF)
    db.add(junk)
    db.commit()
    out = samples.reset_sandbox(db)
    assert out["removed"] >= 1 and len(out["samples"]) == 4
    titles = set(db.scalars(select(Blueprint.title).where(Blueprint.project_id == sandbox.id)))
    assert "visitor junk" not in titles and len(titles) == 4
    assert all(s["score"] is not None for s in out["samples"])
    assert (
        db.scalar(
            select(Node).where(
                Node.embedding.is_(None), Node.blueprint_id.in_([s["id"] for s in out["samples"]])
            )
        )
        is None
    )


def test_demo_login_self_heals_empty_sandbox(client, api, db):
    from app.api.routes import jobs as jobs_route

    queued = []
    client.app.dependency_overrides[jobs_route.get_enqueuer] = lambda: queued.append
    tok = client.post("/api/v1/auth/demo").json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    sandbox = api("get", "/projects", h).json()["items"][0]["id"]
    bps = api("get", f"/projects/{sandbox}/blueprints", h).json()
    assert bps["total"] == 4 and len(queued) == 4  # samples restored, verification queued
    client.post("/api/v1/auth/demo")
    assert api("get", f"/projects/{sandbox}/blueprints", h).json()["total"] == 4  # not doubled

"""Graph storage, edge validation, trace and change-impact propagation."""

import pytest
from sqlalchemy import select

from app.core.errors import AppError
from app.models import Blueprint, ChangeEvent, Node, Project
from app.models.enums import EdgeType, NodeType
from app.services import graph
from app.services.graph import EdgeSpec, NodeSpec


@pytest.fixture
def bp(db):
    project = Project(name="G")
    db.add(project)
    db.flush()
    blueprint = Blueprint(project_id=project.id, title="G", brief="x" * 30)
    db.add(blueprint)
    db.commit()
    return blueprint


def food_graph():
    """REQ1 -> US1 -> MOD1 -> API1 -> ENT1 ; US1 -> TST1 ; API1 -> TST2
    REQ2 -> US2 -> MOD2 ; MOD1 depends_on MOD2 ; RSK1 threatens REQ1
    ENT1 relates_to ENT2 (not followed)"""
    N, T = NodeSpec, NodeType
    nodes = [
        N("REQ1", T.requirement, "Customers can order food", {"kind": "functional"}),
        N("REQ2", T.requirement, "Restaurants manage menus", {"kind": "functional"}),
        N("US1", T.story, "As a customer I place an order", {"acceptance_criteria": ["Given..."]}),
        N("US2", T.story, "As a restaurant I edit my menu", {}),
        N("MOD1", T.module, "Ordering", {}),
        N("MOD2", T.module, "Catalogue", {}),
        N("API1", T.api, "POST /orders", {"method": "POST", "path": "/orders"}),
        N("ENT1", T.entity, "Order", {}),
        N("ENT2", T.entity, "Customer", {}),
        N("TST1", T.test, "Order placed end to end", {}),
        N("TST2", T.test, "POST /orders validates input", {}),
        N("RSK1", T.risk, "Payment provider outage", {}),
    ]
    E = EdgeType
    edges = [
        EdgeSpec("REQ1", "US1", E.refines),
        EdgeSpec("REQ2", "US2", E.refines),
        EdgeSpec("US1", "MOD1", E.implemented_by),
        EdgeSpec("US2", "MOD2", E.implemented_by),
        EdgeSpec("MOD1", "API1", E.exposes),
        EdgeSpec("API1", "ENT1", E.persists),
        EdgeSpec("US1", "TST1", E.verified_by),
        EdgeSpec("API1", "TST2", E.verified_by),
        EdgeSpec("MOD1", "MOD2", E.depends_on),
        EdgeSpec("RSK1", "REQ1", E.threatens),
        EdgeSpec("ENT1", "ENT2", E.relates_to),
    ]
    return nodes, edges


@pytest.fixture
def ids(db, bp):
    nodes, edges = food_graph()
    return graph.replace_graph(db, bp, nodes, edges)


def keys(db, reached):
    by_id = {n.id: n.title for n in db.scalars(select(Node))}
    return {by_id[r.node_id]: r.depth for r in reached}


def test_replace_graph_assigns_sequential_keys(db, bp, ids):
    nodes = {n.title: n.key for n in db.scalars(select(Node).where(Node.blueprint_id == bp.id))}
    assert nodes["Customers can order food"] == "REQ-001"
    assert nodes["Restaurants manage menus"] == "REQ-002"
    assert nodes["POST /orders"] == "API-001"
    assert nodes["Payment provider outage"] == "RSK-001"


def test_impact_from_requirement_reaches_whole_chain_with_depths(db, ids):
    req = db.get(Node, ids["REQ1"])
    got = keys(db, graph.downstream_impact(db, req))
    assert got == {
        "As a customer I place an order": 1,
        "Payment provider outage": 1,  # risk threatens REQ1 -> walked in reverse
        "Ordering": 2,
        "Order placed end to end": 2,
        "POST /orders": 3,
        "Order": 4,
        "POST /orders validates input": 4,
    }
    # relates_to is not followed, and unrelated REQ2 branch is untouched
    assert "Customer" not in got and "Catalogue" not in got


def test_depends_on_propagates_to_dependent_module(db, ids):
    # MOD1 depends on MOD2, so changing MOD2 impacts MOD1 and its subtree.
    got = keys(db, graph.downstream_impact(db, db.get(Node, ids["MOD2"])))
    assert got["Ordering"] == 1
    assert got["POST /orders"] == 2
    assert "Restaurants manage menus" not in got


def test_upstream_trace_from_entity(db, ids):
    got = keys(db, graph.upstream_trace(db, db.get(Node, ids["ENT1"])))
    assert got["POST /orders"] == 1
    assert got["Ordering"] == 2
    assert got["As a customer I place an order"] == 3
    assert got["Customers can order food"] == 4


def test_cycles_terminate(db, bp, ids):
    # Make a depends_on cycle MOD1 <-> MOD2 (allowed by schema, must not loop).
    graph.create_edge(
        db, bp, src_id=ids["MOD2"], dst_id=ids["MOD1"], edge_type=EdgeType.depends_on, body={}
    )
    got = keys(db, graph.downstream_impact(db, db.get(Node, ids["MOD1"])))
    assert got["Catalogue"] == 1
    assert "Ordering" not in got  # root is never reported as its own impact


def test_update_marks_stale_and_records_event_atomically(db, ids):
    req = db.get(Node, ids["REQ1"])
    reached = graph.update_node(
        db, req, user_id=None, title="Customers can order and pay", body=None
    )
    impacted = {r.node_id for r in reached}
    assert ids["US1"] in impacted and ids["TST2"] in impacted
    stale = {n.id for n in db.scalars(select(Node).where(Node.stale.is_(True)))}
    assert stale == impacted
    event = db.scalar(select(ChangeEvent).where(ChangeEvent.node_id == req.id))
    assert event.before["title"] == "Customers can order food"
    assert set(event.impacted) == impacted


def test_noop_update_marks_nothing(db, ids):
    req = db.get(Node, ids["REQ1"])
    assert graph.update_node(db, req, user_id=None, title=req.title, body=None) == []
    assert db.scalar(select(Node).where(Node.stale.is_(True))) is None


@pytest.mark.parametrize(
    ("src", "dst", "etype"),
    [
        ("US1", "REQ1", EdgeType.refines),  # wrong direction
        ("REQ1", "API1", EdgeType.exposes),  # wrong types
        ("TST1", "US1", EdgeType.verified_by),
    ],
)
def test_invalid_edges_rejected(db, bp, ids, src, dst, etype):
    with pytest.raises(AppError) as exc:
        graph.create_edge(db, bp, src_id=ids[src], dst_id=ids[dst], edge_type=etype, body={})
    assert exc.value.code == "INVALID_EDGE"


def test_replace_graph_is_all_or_nothing(db, bp, ids):
    before = db.scalars(select(Node.id).where(Node.blueprint_id == bp.id)).all()
    nodes = [NodeSpec("A", NodeType.requirement, "a", {}), NodeSpec("B", NodeType.api, "b", {})]
    with pytest.raises(AppError):
        graph.replace_graph(db, bp, nodes, [EdgeSpec("A", "B", EdgeType.refines)])
    after = db.scalars(select(Node.id).where(Node.blueprint_id == bp.id)).all()
    assert sorted(before) == sorted(after)


def test_replace_graph_rejects_unknown_refs_and_dupes(db, bp):
    n = [NodeSpec("A", NodeType.requirement, "a", {})]
    with pytest.raises(AppError):
        graph.replace_graph(db, bp, n, [EdgeSpec("A", "ZZZ", EdgeType.refines)])
    with pytest.raises(AppError):
        graph.replace_graph(db, bp, n + n, [])


def test_status_only_for_trackable(db, ids):
    from app.models.enums import NodeStatus

    with pytest.raises(AppError) as exc:
        graph.set_status(db, db.get(Node, ids["REQ1"]), NodeStatus.done)
    assert exc.value.code == "NOT_TRACKABLE"
    assert graph.set_status(db, db.get(Node, ids["US1"]), NodeStatus.done).status == NodeStatus.done


# ----------------------------------------------------------- through the HTTP API


@pytest.fixture
def owner_bp(api, make_user, login):
    h = login(make_user())
    pid = api("post", "/projects", h, json={"name": "API"}).json()["id"]
    bp = api(
        "post",
        f"/projects/{pid}/blueprints",
        h,
        json={"title": "B", "brief": "A hospital appointment booking system."},
    ).json()["id"]
    return h, bp


def test_http_build_graph_edit_and_see_impact(api, owner_bp):
    h, bp = owner_bp

    def node(t, title):
        r = api("post", f"/blueprints/{bp}/nodes", h, json={"type": t, "title": title})
        assert r.status_code == 201, r.text
        return r.json()

    req, story, mod = (
        node("requirement", "Book appointments"),
        node("story", "Patient books"),
        node("module", "Scheduling"),
    )
    assert req["key"] == "REQ-001" and story["key"] == "US-001"
    for s, d, t in [(req, story, "refines"), (story, mod, "implemented_by")]:
        r = api(
            "post",
            f"/blueprints/{bp}/edges",
            h,
            json={"src_id": s["id"], "dst_id": d["id"], "type": t},
        )
        assert r.status_code == 201, r.text
    dup = api(
        "post",
        f"/blueprints/{bp}/edges",
        h,
        json={"src_id": req["id"], "dst_id": story["id"], "type": "refines"},
    )
    assert dup.status_code == 409

    dry = api("get", f"/nodes/{req['id']}/impact", h).json()
    assert [i["key"] for i in dry["impacted"]] == ["US-001", "MOD-001"]
    assert api("get", f"/blueprints/{bp}/graph?stale=true", h).json()["nodes"] == []

    r = api("patch", f"/nodes/{req['id']}", h, json={"title": "Book and cancel appointments"})
    assert r.status_code == 200
    impact = r.json()["impact"]
    assert impact["by_depth"] == {"1": [story["id"]], "2": [mod["id"]]}
    stale = api("get", f"/blueprints/{bp}/graph?stale=true", h).json()["nodes"]
    assert {n["key"] for n in stale} == {"US-001", "MOD-001"}

    trace = api("get", f"/nodes/{mod['id']}/trace", h).json()
    assert [u["key"] for u in trace["upstream"]] == ["US-001", "REQ-001"]

    graph_all = api("get", f"/blueprints/{bp}/graph?types=requirement&types=story", h).json()
    assert {n["type"] for n in graph_all["nodes"]} == {"requirement", "story"}
    assert len(graph_all["edges"]) == 1  # only edges whose both ends are visible


def test_http_invalid_edge_and_cross_blueprint(api, owner_bp, make_user, login):
    h, bp = owner_bp
    a = api("post", f"/blueprints/{bp}/nodes", h, json={"type": "test", "title": "t"}).json()
    b = api("post", f"/blueprints/{bp}/nodes", h, json={"type": "story", "title": "s"}).json()
    r = api(
        "post",
        f"/blueprints/{bp}/edges",
        h,
        json={"src_id": a["id"], "dst_id": b["id"], "type": "verified_by"},
    )
    assert r.status_code == 400 and r.json()["code"] == "INVALID_EDGE"
    assert "story->test" in r.json()["details"]["allowed"]


def test_http_duplicate_key_and_pagination(api, owner_bp):
    h, bp = owner_bp
    for i in range(3):
        api("post", f"/blueprints/{bp}/nodes", h, json={"type": "requirement", "title": f"r{i}"})
    dup = api(
        "post",
        f"/blueprints/{bp}/nodes",
        h,
        json={"type": "requirement", "title": "x", "key": "REQ-002"},
    )
    assert dup.status_code == 409
    page = api("get", f"/blueprints/{bp}/nodes?limit=2&offset=1&type=requirement", h).json()
    assert page["total"] == 3 and [n["key"] for n in page["items"]] == ["REQ-002", "REQ-003"]


def test_http_delete_node_cascades_edges(api, owner_bp):
    h, bp = owner_bp
    a = api("post", f"/blueprints/{bp}/nodes", h, json={"type": "requirement", "title": "a"}).json()
    b = api("post", f"/blueprints/{bp}/nodes", h, json={"type": "story", "title": "b"}).json()
    api(
        "post",
        f"/blueprints/{bp}/edges",
        h,
        json={"src_id": a["id"], "dst_id": b["id"], "type": "refines"},
    )
    assert api("delete", f"/nodes/{a['id']}", h).status_code == 204
    g = api("get", f"/blueprints/{bp}/graph", h).json()
    assert len(g["nodes"]) == 1 and g["edges"] == []
    assert api("get", f"/nodes/{a['id']}", h).status_code == 404

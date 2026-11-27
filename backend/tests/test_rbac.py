"""RBAC matrix: every role x every protected action, enforced server-side."""

import pytest

BRIEF = "A food delivery app where customers order from nearby restaurants and track riders."


@pytest.fixture
def world(api, make_user, login):
    """A project with an owner, editor, viewer, an outsider and an admin."""
    users = {name: make_user() for name in ("owner", "editor", "viewer", "outsider")}
    users["admin"] = make_user(admin=True)
    h = {name: login(u) for name, u in users.items()}
    pid = api("post", "/projects", h["owner"], json={"name": "P"}).json()["id"]
    for role in ("editor", "viewer"):
        r = api(
            "post",
            f"/projects/{pid}/members",
            h["owner"],
            json={"email": users[role].email, "role": role},
        )
        assert r.status_code == 201
    bp = api(
        "post", f"/projects/{pid}/blueprints", h["owner"], json={"title": "B", "brief": BRIEF}
    ).json()["id"]
    node = api(
        "post",
        f"/blueprints/{bp}/nodes",
        h["owner"],
        json={"type": "story", "title": "As a user I order food"},
    ).json()["id"]
    return {"h": h, "users": users, "pid": pid, "bp": bp, "node": node}


# (method, path template, json, minimum role)
ACTIONS = [
    ("get", "/projects/{pid}", None, "viewer"),
    ("get", "/projects/{pid}/members", None, "viewer"),
    ("get", "/projects/{pid}/blueprints", None, "viewer"),
    ("get", "/blueprints/{bp}", None, "viewer"),
    ("get", "/blueprints/{bp}/graph", None, "viewer"),
    ("get", "/nodes/{node}/trace", None, "viewer"),
    ("get", "/nodes/{node}/impact", None, "viewer"),
    ("post", "/projects/{pid}/blueprints", {"title": "B2", "brief": BRIEF}, "editor"),
    ("patch", "/blueprints/{bp}", {"title": "Renamed"}, "editor"),
    ("post", "/blueprints/{bp}/nodes", {"type": "requirement", "title": "R"}, "editor"),
    ("patch", "/nodes/{node}", {"title": "Edited"}, "editor"),
    ("patch", "/nodes/{node}/status", {"status": "in_progress"}, "editor"),
    ("patch", "/projects/{pid}", {"name": "New name"}, "owner"),
    ("delete", "/blueprints/{bp}", None, "owner"),
]
RANK = {"viewer": 1, "editor": 2, "owner": 3}


@pytest.mark.parametrize("role", ["viewer", "editor", "owner", "admin", "outsider"])
@pytest.mark.parametrize(("method", "path", "body", "min_role"), ACTIONS)
def test_rbac_matrix(world, api, role, method, path, body, min_role):
    url = path.format(**world)
    kwargs = {"json": body} if body is not None else {}
    r = api(method, url, world["h"][role], **kwargs)
    if role == "admin" or (role != "outsider" and RANK[role] >= RANK[min_role]):
        assert r.status_code in (200, 201, 204), (role, method, url, r.text)
    elif role == "outsider":
        assert r.status_code == 404, (role, method, url, r.text)  # existence not leaked
    else:
        assert r.status_code == 403, (role, method, url, r.text)
        assert r.json()["code"] == "FORBIDDEN"


def test_only_owner_manages_members(world, api):
    pid, h, users = world["pid"], world["h"], world["users"]
    r = api(
        "post",
        f"/projects/{pid}/members",
        h["editor"],
        json={"email": users["outsider"].email, "role": "viewer"},
    )
    assert r.status_code == 403
    r = api(
        "post",
        f"/projects/{pid}/members",
        h["owner"],
        json={"email": users["outsider"].email, "role": "viewer"},
    )
    assert r.status_code == 201
    r = api(
        "post",
        f"/projects/{pid}/members",
        h["owner"],
        json={"email": users["outsider"].email, "role": "viewer"},
    )
    assert r.status_code == 409


def test_cannot_remove_or_demote_last_owner(world, api):
    pid, h, users = world["pid"], world["h"], world["users"]
    owner_id = str(users["owner"].id)
    r = api("delete", f"/projects/{pid}/members/{owner_id}", h["owner"])
    assert r.status_code == 400 and r.json()["code"] == "LAST_OWNER"
    r = api("patch", f"/projects/{pid}/members/{owner_id}", h["owner"], json={"role": "viewer"})
    assert r.json()["code"] == "LAST_OWNER"
    # promote editor to owner, then the original owner may step down
    editor_id = str(users["editor"].id)
    assert (
        api(
            "patch", f"/projects/{pid}/members/{editor_id}", h["owner"], json={"role": "owner"}
        ).status_code
        == 200
    )
    assert (
        api(
            "patch", f"/projects/{pid}/members/{owner_id}", h["owner"], json={"role": "viewer"}
        ).status_code
        == 200
    )


def test_member_role_change_takes_effect(world, api):
    pid, h, users = world["pid"], world["h"], world["users"]
    viewer_id = str(users["viewer"].id)
    assert (
        api("patch", f"/blueprints/{world['bp']}", h["viewer"], json={"title": "x"}).status_code
        == 403
    )
    api("patch", f"/projects/{pid}/members/{viewer_id}", h["owner"], json={"role": "editor"})
    assert (
        api("patch", f"/blueprints/{world['bp']}", h["viewer"], json={"title": "x"}).status_code
        == 200
    )


def test_removed_member_loses_access(world, api):
    pid, h = world["pid"], world["h"]
    vid = str(world["users"]["viewer"].id)
    assert api("delete", f"/projects/{pid}/members/{vid}", h["owner"]).status_code == 204
    assert api("get", f"/projects/{pid}", h["viewer"]).status_code == 404


def test_project_list_only_shows_membership(world, api):
    assert api("get", "/projects", world["h"]["outsider"]).json()["total"] == 0
    assert api("get", "/projects", world["h"]["viewer"]).json()["total"] == 1
    assert api("get", "/projects", world["h"]["admin"]).json()["total"] >= 1


def test_admin_endpoint(world, api):
    assert api("get", "/admin/users", world["h"]["owner"]).status_code == 403
    r = api("get", "/admin/users", world["h"]["admin"])
    assert r.status_code == 200 and r.json()["total"] >= 5


def test_owner_can_delete_project_but_not_sandbox(world, api, client):
    assert api("delete", f"/projects/{world['pid']}", world["h"]["editor"]).status_code == 403
    assert api("delete", f"/projects/{world['pid']}", world["h"]["owner"]).status_code == 204
    demo = client.post("/api/v1/auth/demo").json()["access_token"]
    sandbox = api("get", "/projects", {"Authorization": f"Bearer {demo}"}).json()["items"][0]
    r = api("delete", f"/projects/{sandbox['id']}", world["h"]["admin"])
    assert r.status_code == 403 and r.json()["code"] == "SANDBOX_PROTECTED"


ZERO = "00000000-0000-0000-0000-000000000000"


@pytest.mark.parametrize(
    "path",
    [f"/projects/{ZERO}", f"/blueprints/{ZERO}", f"/nodes/{ZERO}", f"/nodes/{ZERO}/trace"],
)
def test_missing_resources_are_404_for_admins_too(world, api, path):
    for role in ("owner", "admin"):
        r = api("get", path, world["h"][role])
        assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("viewer", 403),
        ("outsider", 404),
        ("editor", 204),
        ("admin", 204),
    ],
)
def test_edge_delete_rbac(world, api, role, expected):
    h = world["h"]["owner"]
    req = api(
        "post", f"/blueprints/{world['bp']}/nodes", h, json={"type": "requirement", "title": "R"}
    ).json()
    edge = api(
        "post",
        f"/blueprints/{world['bp']}/edges",
        h,
        json={"src_id": req["id"], "dst_id": world["node"], "type": "refines"},
    ).json()
    assert api("delete", f"/edges/{edge['id']}", world["h"][role]).status_code == expected
    if expected == 204:
        assert api("delete", f"/edges/{edge['id']}", h).status_code == 404  # gone


def test_admin_sees_any_project_without_membership(world, api):
    r = api("get", f"/projects/{world['pid']}", world["h"]["admin"])
    assert r.status_code == 200 and r.json()["my_role"] is None

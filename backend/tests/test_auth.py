from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_refresh_token
from app.models import RefreshToken

REFRESH = "/api/v1/auth/refresh"


def test_register_login_me(client, api):
    r = api(
        "post",
        "/auth/register",
        json={"email": "new@example.com", "password": "longenough1", "display_name": "New"},
    )
    assert r.status_code == 201
    assert "sf_refresh" in r.cookies
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = api("get", "/me", headers)
    assert me.status_code == 200
    assert me.json()["email"] == "new@example.com"
    assert "password_hash" not in me.json()


def test_register_duplicate_email_conflict(api, make_user):
    user = make_user()
    r = api(
        "post",
        "/auth/register",
        json={"email": user.email, "password": "longenough1", "display_name": "X"},
    )
    assert r.status_code == 409
    assert r.json()["code"] == "EMAIL_TAKEN"


def test_register_validation_error_format(api):
    r = api("post", "/auth/register", json={"email": "not-an-email", "password": "x"})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert set(body) == {"code", "message", "details"}
    assert body["details"]["errors"]


def test_login_wrong_password_and_unknown_user_look_identical(api, make_user):
    user = make_user()
    a = api("post", "/auth/login", json={"email": user.email, "password": "wrong-password"})
    b = api("post", "/auth/login", json={"email": "ghost@example.com", "password": "whatever1"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_missing_and_bad_tokens(api):
    assert api("get", "/me").json()["code"] == "TOKEN_MISSING"
    r = api("get", "/me", {"Authorization": "Bearer garbage"})
    assert r.status_code == 401 and r.json()["code"] == "TOKEN_INVALID"


def test_expired_access_token(api, make_user):
    user = make_user()
    s = get_settings()
    token = jwt.encode(
        {"sub": str(user.id), "typ": "access", "exp": datetime.now(UTC) - timedelta(seconds=5)},
        s.jwt_secret,
        algorithm=s.jwt_algorithm,
    )
    r = api("get", "/me", {"Authorization": f"Bearer {token}"})
    assert r.status_code == 401 and r.json()["code"] == "TOKEN_EXPIRED"


def test_token_signed_with_other_key_rejected(api, make_user):
    user = make_user()
    token = jwt.encode(
        {"sub": str(user.id), "typ": "access", "exp": datetime.now(UTC) + timedelta(minutes=5)},
        "attacker-key-attacker-key-attacker-key",
        algorithm="HS256",
    )
    assert api("get", "/me", {"Authorization": f"Bearer {token}"}).status_code == 401


def test_refresh_rotates_and_reuse_revokes_family(client, make_user, login, db):
    user = make_user()
    login(user)
    first = client.cookies.get("sf_refresh")
    r1 = client.post(REFRESH)
    assert r1.status_code == 200
    second = client.cookies.get("sf_refresh")
    assert second and second != first

    # Replay the old (now revoked) token -> reuse detected, family revoked.
    client.cookies.set("sf_refresh", first, path="/api/v1/auth")
    r2 = client.post(REFRESH)
    assert r2.status_code == 401 and r2.json()["code"] == "REFRESH_REUSED"

    # The legitimately rotated token is now dead too.
    client.cookies.set("sf_refresh", second, path="/api/v1/auth")
    r3 = client.post(REFRESH)
    assert r3.status_code == 401
    tokens = db.scalars(select(RefreshToken).where(RefreshToken.user_id == user.id)).all()
    assert tokens and all(t.revoked_at is not None for t in tokens)


def test_refresh_expired(client, make_user, login, db):
    user = make_user()
    login(user)
    raw = client.cookies.get("sf_refresh")
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw)))
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    r = client.post(REFRESH)
    assert r.status_code == 401 and r.json()["code"] == "REFRESH_EXPIRED"


def test_refresh_missing_cookie(client):
    r = client.post(REFRESH)
    assert r.status_code == 401 and r.json()["code"] == "REFRESH_MISSING"


def test_logout_revokes_refresh(client, make_user, login):
    login(make_user())
    raw = client.cookies.get("sf_refresh")
    assert client.post("/api/v1/auth/logout").status_code == 204
    client.cookies.set("sf_refresh", raw, path="/api/v1/auth")
    assert client.post(REFRESH).status_code == 401


def test_refresh_tokens_stored_hashed(client, make_user, login, db):
    user = make_user()
    login(user)
    raw = client.cookies.get("sf_refresh")
    hashes = db.scalars(select(RefreshToken.token_hash).where(RefreshToken.user_id == user.id))
    assert raw not in list(hashes)


def test_demo_login_gives_editor_on_sandbox(api):
    r = api("post", "/auth/demo")
    assert r.status_code == 200
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    projects = api("get", "/projects", h).json()["items"]
    assert len(projects) == 1
    assert projects[0]["is_sandbox"] is True and projects[0]["my_role"] == "editor"
    # second demo login reuses the same user + sandbox
    r2 = api("post", "/auth/demo")
    h2 = {"Authorization": f"Bearer {r2.json()['access_token']}"}
    assert api("get", "/projects", h2).json()["total"] == 1


def test_demo_user_cannot_password_login(api):
    api("post", "/auth/demo")
    r = api("post", "/auth/login", json={"email": get_settings().demo_email, "password": "x"})
    assert r.status_code == 401


def test_demo_user_cannot_create_projects(api):
    h = {"Authorization": f"Bearer {api('post', '/auth/demo').json()['access_token']}"}
    r = api("post", "/projects", h, json={"name": "mine"})
    assert r.status_code == 403 and r.json()["code"] == "DEMO_READ_ONLY"


def test_passwords_hashed_with_argon2id(make_user):
    assert make_user().password_hash.startswith("$argon2id$")

"""Health probes, error envelope, security headers, metrics, config guards."""

import pytest

from app.api.routes import health
from app.core.config import DEV_SECRET, Settings


def test_health_has_no_dependencies(client, monkeypatch):
    monkeypatch.setattr(health, "check_db", lambda: pytest.fail("liveness must not hit the DB"))
    assert client.get("/health").json() == {"status": "ok"}


def test_ready_ok(client, monkeypatch):
    monkeypatch.setattr(health, "check_redis", lambda: {"ok": True})
    r = client.get("/ready")
    assert r.status_code == 200 and r.json()["status"] == "ready"


def test_ready_503_when_redis_down(client, monkeypatch):
    monkeypatch.setattr(health, "check_redis", lambda: {"ok": False, "error": "redis unreachable"})
    r = client.get("/ready")
    assert r.status_code == 503
    assert r.json()["checks"]["redis"]["ok"] is False
    assert r.json()["checks"]["database"]["ok"] is True


def test_real_redis_check_reports_failure_quickly(monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.get_settings(), "redis_url", "redis://127.0.0.1:1/0")
    assert health.check_redis()["ok"] is False


def test_status_page_payload(client):
    body = client.get("/api/v1/status").json()
    assert {"version", "commit", "components", "ci_run_url"} <= set(body)
    assert body["components"]["api"]["ok"] is True


def test_security_headers_and_request_id(client):
    r = client.get("/health", headers={"X-Request-ID": "abc123"})
    assert r.headers["X-Request-ID"] == "abc123"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    generated = client.get("/health").headers["X-Request-ID"]
    assert len(generated) == 32


def test_not_found_uses_error_envelope(client):
    r = client.get("/api/v1/does-not-exist")
    assert r.status_code == 404
    assert r.json() == {"code": "NOT_FOUND", "message": "Not Found", "details": {}}


def test_unhandled_exception_hides_internals(db):
    from fastapi.testclient import TestClient

    from app.db.session import get_db
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_db] = lambda: db

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret internal detail")

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/boom")
    assert r.status_code == 500
    assert r.json()["code"] == "INTERNAL_ERROR"
    assert "secret" not in r.text


def test_metrics_endpoint(client):
    client.get("/health")
    text = client.get("/metrics").text
    assert "specforge_http_request_duration_seconds" in text


def test_openapi_docs_available(client):
    assert client.get("/docs").status_code == 200
    spec = client.get("/openapi.json").json()
    assert "/api/v1/nodes/{node_id}/impact" in spec["paths"]


def test_cors_allows_frontend_origin_only(client):
    ok = client.options(
        "/api/v1/me",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options(
        "/api/v1/me",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in bad.headers


def test_production_refuses_dev_secret():
    with pytest.raises(ValueError):
        Settings(environment="production", jwt_secret=DEV_SECRET)
    with pytest.raises(ValueError):
        Settings(environment="production", jwt_secret="short")
    assert Settings(environment="production", jwt_secret="x" * 40).environment == "production"

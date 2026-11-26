"""HTTP: generation submission (idempotency, RBAC, rate limits, queue down) and SSE."""

import json
import threading
import time

import pytest
import redis as redis_lib

from app.api.routes import jobs as jobs_route
from app.core.config import get_settings
from app.models import Job
from app.models.enums import JobStatus
from app.services import jobs as job_service
from tests.llm_fakes import FOOD_BRIEF


@pytest.fixture
def enqueued(client):
    calls = []
    client.app.dependency_overrides[jobs_route.get_enqueuer] = lambda: calls.append
    return calls


@pytest.fixture
def setup(api, make_user, login):
    owner, viewer = make_user(), make_user()
    h = login(owner)
    pid = api("post", "/projects", h, json={"name": "P"}).json()["id"]
    api("post", f"/projects/{pid}/members", h, json={"email": viewer.email, "role": "viewer"})
    bp = api(
        "post", f"/projects/{pid}/blueprints", h, json={"title": "Food", "brief": FOOD_BRIEF}
    ).json()["id"]
    return {"h": h, "hv": login(viewer), "bp": bp, "pid": pid}


def test_editor_submits_job(api, setup, enqueued):
    r = api("post", f"/blueprints/{setup['bp']}/generate", setup["h"])
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued" and body["kind"] == "generate"
    assert len(enqueued) == 1 and str(enqueued[0].id) == body["job_id"]
    got = api("get", f"/jobs/{body['job_id']}", setup["hv"])
    assert got.status_code == 200 and got.json()["job_id"] == body["job_id"]
    assert len(api("get", f"/blueprints/{setup['bp']}/jobs", setup["hv"]).json()) == 1


def test_viewer_cannot_generate(api, setup, enqueued):
    r = api("post", f"/blueprints/{setup['bp']}/generate", setup["hv"])
    assert r.status_code == 403 and enqueued == []


def test_idempotency_key_returns_same_job(api, setup, enqueued, db):
    h = {**setup["h"], "Idempotency-Key": "abc-123"}
    first = api("post", f"/blueprints/{setup['bp']}/generate", h)
    # finish it so the "active job" rule doesn't also apply
    job = db.get(Job, __import__("uuid").UUID(first.json()["job_id"]))
    job.status = JobStatus.succeeded
    db.commit()
    second = api("post", f"/blueprints/{setup['bp']}/generate", h)
    assert second.status_code == 200 and second.json()["job_id"] == first.json()["job_id"]
    assert len(enqueued) == 1


def test_idempotency_key_reuse_on_other_blueprint_conflicts(api, setup, enqueued):
    h = {**setup["h"], "Idempotency-Key": "same-key"}
    api("post", f"/blueprints/{setup['bp']}/generate", h)
    other = api(
        "post",
        f"/projects/{setup['pid']}/blueprints",
        setup["h"],
        json={"title": "Other", "brief": FOOD_BRIEF},
    ).json()["id"]
    r = api("post", f"/blueprints/{other}/generate", h)
    assert r.status_code == 409 and r.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_running_job_is_returned_instead_of_duplicate(api, setup, enqueued):
    a = api("post", f"/blueprints/{setup['bp']}/generate", setup["h"])
    b = api("post", f"/blueprints/{setup['bp']}/generate", setup["h"])
    assert b.status_code == 200 and a.json()["job_id"] == b.json()["job_id"]
    assert len(enqueued) == 1


def test_queue_down_returns_503_and_marks_job_failed(api, setup, client, db):
    def broken(job):
        raise ConnectionError("redis down")

    client.app.dependency_overrides[jobs_route.get_enqueuer] = lambda: broken
    r = api("post", f"/blueprints/{setup['bp']}/generate", setup["h"])
    assert r.status_code == 503 and r.json()["code"] == "QUEUE_UNAVAILABLE"
    job = db.query(Job).one()
    assert job.status == JobStatus.failed


def test_rate_limit_per_user(api, setup, enqueued, monkeypatch, db):
    monkeypatch.setattr(get_settings(), "generate_limit_per_user_hour", 2)
    for _ in range(2):
        assert api("post", f"/blueprints/{setup['bp']}/generate", setup["h"]).status_code == 202
        db.query(Job).update({Job.status: JobStatus.succeeded})
        db.commit()
    r = api("post", f"/blueprints/{setup['bp']}/generate", setup["h"])
    assert r.status_code == 429
    body = r.json()
    assert body["code"] == "RATE_LIMITED" and body["details"]["scope"] == "user"
    assert "sample blueprints" in body["message"]
    assert int(r.headers["Retry-After"]) > 0


def test_demo_users_are_limited_per_ip(api, client, enqueued, monkeypatch):
    monkeypatch.setattr(get_settings(), "generate_limit_per_ip_hour", 1)
    demo = {"Authorization": f"Bearer {client.post('/api/v1/auth/demo').json()['access_token']}"}
    sandbox = api("get", "/projects", demo).json()["items"][0]["id"]
    bp1 = api(
        "post", f"/projects/{sandbox}/blueprints", demo, json={"title": "A", "brief": FOOD_BRIEF}
    ).json()["id"]
    bp2 = api(
        "post", f"/projects/{sandbox}/blueprints", demo, json={"title": "B", "brief": FOOD_BRIEF}
    ).json()["id"]
    assert api("post", f"/blueprints/{bp1}/generate", demo).status_code == 202
    r = api("post", f"/blueprints/{bp2}/generate", demo)
    assert r.status_code == 429 and r.json()["details"]["scope"] == "ip"


def test_demo_login_rate_limited(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "demo_login_limit_per_ip_hour", 2)
    codes = [client.post("/api/v1/auth/demo").status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_rate_limiter_down_is_503_not_unmetered(api, setup, enqueued, monkeypatch):
    monkeypatch.setattr(get_settings(), "redis_url", "redis://127.0.0.1:1/0")
    r = api("post", f"/blueprints/{setup['bp']}/generate", setup["h"])
    assert r.status_code == 503 and r.json()["code"] == "RATE_LIMITER_UNAVAILABLE"
    assert enqueued == []


def test_outsider_cannot_see_job(api, setup, enqueued, make_user, login):
    job_id = api("post", f"/blueprints/{setup['bp']}/generate", setup["h"]).json()["job_id"]
    assert api("get", f"/jobs/{job_id}", login(make_user())).status_code == 404
    assert api("get", f"/jobs/{job_id}/events", login(make_user())).status_code == 404


# ------------------------------------------------------------------ SSE


@pytest.fixture
def sse_reads_test_db(db, monkeypatch):
    def read(job_id):
        db.expire_all()
        job = db.get(Job, job_id)
        return job_service.job_event(job) if job else None

    monkeypatch.setattr(jobs_route, "read_job", read)


def _events(lines):
    out = []
    for line in lines:
        if line.startswith("data: "):
            out.append(json.loads(line[6:]))
    return out


def test_sse_finished_job_sends_one_event_and_closes(
    client, api, setup, enqueued, db, sse_reads_test_db
):
    job_id = api("post", f"/blueprints/{setup['bp']}/generate", setup["h"]).json()["job_id"]
    db.query(Job).update({Job.status: JobStatus.succeeded, Job.progress: 100, Job.step: "done"})
    db.commit()
    with client.stream("GET", f"/api/v1/jobs/{job_id}/events", headers=setup["h"]) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        events = _events(r.iter_lines())
    assert [e["status"] for e in events] == ["succeeded"]


def test_sse_streams_pubsub_progress_until_done(
    client, api, setup, enqueued, db, sse_reads_test_db
):
    job_id = api("post", f"/blueprints/{setup['bp']}/generate", setup["h"]).json()["job_id"]
    base = {
        "job_id": job_id,
        "blueprint_id": setup["bp"],
        "kind": "generate",
        "result": None,
        "error": None,
    }
    r = redis_lib.Redis.from_url(get_settings().redis_url)
    channel = job_service.CHANNEL.format(job_id)

    def worker():
        time.sleep(0.5)
        for step, pct, status in [("generating_design", 40, "running"), ("done", 100, "succeeded")]:
            r.publish(
                channel, json.dumps({**base, "status": status, "step": step, "progress": pct})
            )
            time.sleep(0.2)

    t = threading.Thread(target=worker)
    t.start()
    with client.stream("GET", f"/api/v1/jobs/{job_id}/events", headers=setup["h"]) as resp:
        events = _events(resp.iter_lines())
    t.join()
    assert [e["step"] for e in events] == ["queued", "generating_design", "done"]
    assert events[-1]["progress"] == 100


def test_sse_without_redis_polls_database(client, api, setup, enqueued, db, monkeypatch):
    job_id = api("post", f"/blueprints/{setup['bp']}/generate", setup["h"]).json()["job_id"]
    states = iter(
        [("queued", 0, "queued"), ("generating_tests", 65, "running"), ("done", 100, "succeeded")]
    )

    def read(_):
        try:
            step, pct, status = next(states)
        except StopIteration:
            step, pct, status = "done", 100, "succeeded"
        return {
            "job_id": job_id,
            "blueprint_id": setup["bp"],
            "kind": "generate",
            "status": status,
            "step": step,
            "progress": pct,
            "result": None,
            "error": None,
        }

    monkeypatch.setattr(jobs_route, "read_job", read)
    monkeypatch.setattr(get_settings(), "redis_url", "redis://127.0.0.1:1/0")
    with client.stream("GET", f"/api/v1/jobs/{job_id}/events", headers=setup["h"]) as resp:
        events = _events(resp.iter_lines())
    assert [e["status"] for e in events] == ["queued", "running", "succeeded"]


def test_status_lists_llm_chain(client):
    body = client.get("/api/v1/status").json()
    assert body["llm_chain"][-2:] == ["cache", "demo"]
    assert body["llm_providers"]["demo"]["configured"] is True
    assert body["llm_providers"]["gemini"]["configured"] is False  # keys blanked in tests

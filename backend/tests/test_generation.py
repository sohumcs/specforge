"""Generation pipeline + Celery task behaviour (retries, DLQ, idempotent redelivery)."""

import json
import uuid

import pytest
import redis as redis_lib
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.llm.breaker import MemoryBreaker
from app.llm.providers.base import ProviderUnavailable
from app.models import Blueprint, GenerationCache, Job, Node, Project, User
from app.models.enums import BlueprintStatus, JobKind, JobStatus, NodeType
from app.services import generation
from app.services.generation import brief_hash, cache_key, run_generation
from app.worker import tasks
from tests.llm_fakes import FOOD_BRIEF, ScriptedProvider, valid_draft


@pytest.fixture
def bp(db):
    project = Project(name="Gen")
    db.add(project)
    db.flush()
    blueprint = Blueprint(project_id=project.id, title="Food", brief=FOOD_BRIEF)
    db.add(blueprint)
    db.commit()
    return blueprint


def steps_log():
    log = []
    return log, lambda step, pct, extra: log.append((step, pct))


def test_generation_stores_graph_and_caches(db, bp):
    log, report = steps_log()
    p = ScriptedProvider("gemini")
    summary = run_generation(db, bp, report, providers=[p], breaker=MemoryBreaker())
    assert summary["provider"] == "gemini" and summary["nodes"] > 20
    assert bp.status == BlueprintStatus.ready and bp.provider == "gemini" and bp.version == 2
    types = {n.type for n in db.scalars(select(Node).where(Node.blueprint_id == bp.id))}
    assert types == set(NodeType)
    assert next(s for s, _ in log) == "parsing" and log[-1][0] == "saving"
    row = db.get(GenerationCache, cache_key(FOOD_BRIEF, {}))
    assert row is not None and row.brief_hash == brief_hash(FOOD_BRIEF)

    # Same brief again: served from cache, no LLM calls.
    p2 = ScriptedProvider("gemini")
    again = run_generation(db, bp, report, providers=[p2], breaker=MemoryBreaker())
    assert again["provider"] == "cache" and p2.requests == []
    # force=True bypasses the cache.
    p3 = ScriptedProvider("gemini")
    run_generation(db, bp, report, force=True, providers=[p3], breaker=MemoryBreaker())
    assert len(p3.requests) == 3


def test_cache_key_normalises_whitespace_and_case():
    assert cache_key("Hello   World", {}) == cache_key(" hello world ", {})
    assert cache_key("hello world", {}) != cache_key("hello world", {"x": 1})


def test_demo_fallback_is_not_cached(db, bp):
    down = ScriptedProvider("gemini", [ProviderUnavailable("down")])
    summary = run_generation(db, bp, lambda *a: None, providers=[down], breaker=MemoryBreaker())
    assert summary["provider"] == "demo"
    assert summary["fallback_attempts"][0]["outcome"] == "unavailable"
    assert db.get(GenerationCache, cache_key(FOOD_BRIEF, {})) is None
    assert db.scalar(select(Node).where(Node.blueprint_id == bp.id)) is not None


def test_stale_cache_used_when_llms_down(db, bp):
    db.add(
        GenerationCache(
            cache_key="old-version-key",
            brief_hash=brief_hash(FOOD_BRIEF),
            prompt_version="v0",
            provider="gemini",
            payload=valid_draft().model_dump(),
        )
    )
    db.commit()
    down = ScriptedProvider("gemini", [ProviderUnavailable("down")])
    summary = run_generation(db, bp, lambda *a: None, providers=[down], breaker=MemoryBreaker())
    assert summary["provider"] == "cache"


# ------------------------------------------------------------------ Celery task


@pytest.fixture
def job(db, bp):
    user = User(email="t@example.com", display_name="T", password_hash="x")
    db.add(user)
    db.flush()
    j = Job(blueprint_id=bp.id, user_id=user.id, kind=JobKind.generate, params={})
    db.add(j)
    db.commit()
    return j


@pytest.fixture
def task_db(db, monkeypatch):
    """Make the task open sessions on the test transaction."""
    conn = db.connection()
    monkeypatch.setattr(
        tasks,
        "session_factory",
        lambda: Session(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        ),
    )
    return db


def _fake_generation(monkeypatch, fn):
    monkeypatch.setattr(tasks, "run_generation", fn)


def test_task_success_records_result(task_db, job, monkeypatch):
    monkeypatch.setattr(generation, "default_providers", lambda: [ScriptedProvider("gemini")])
    monkeypatch.setattr(generation, "RedisBreaker", MemoryBreaker)
    tasks.generate_blueprint.apply(args=[str(job.id)])
    task_db.refresh(job)
    assert job.status == JobStatus.succeeded and job.progress == 100 and job.step == "done"
    assert job.result["provider"] == "gemini" and job.attempts == 1


def test_task_is_noop_for_finished_job(task_db, job, monkeypatch):
    job.status = JobStatus.succeeded
    task_db.commit()
    _fake_generation(monkeypatch, lambda *a, **k: pytest.fail("must not run"))
    tasks.generate_blueprint.apply(args=[str(job.id)])


def test_task_resumes_interrupted_running_job(task_db, job, monkeypatch):
    job.status, job.attempts = JobStatus.running, 1  # worker died mid-job
    task_db.commit()
    _fake_generation(monkeypatch, lambda *a, **k: {"provider": "demo"})
    tasks.generate_blueprint.apply(args=[str(job.id)])
    task_db.refresh(job)
    assert job.status == JobStatus.succeeded and job.attempts == 2


def test_task_unexpected_error_marks_failed_without_leaking(task_db, job, monkeypatch, bp):
    def boom(*a, **k):
        raise RuntimeError("secret stack detail")

    _fake_generation(monkeypatch, boom)
    tasks.generate_blueprint.apply(args=[str(job.id)])
    task_db.refresh(job)
    task_db.refresh(bp)
    assert job.status == JobStatus.failed and job.error["code"] == "JOB_FAILED"
    assert "secret" not in json.dumps(job.error)
    assert bp.status == BlueprintStatus.failed


def test_task_transient_errors_retry_then_dead_letter(task_db, job, monkeypatch):
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        raise OperationalError("SELECT 1", {}, Exception("db blip"))

    _fake_generation(monkeypatch, flaky)
    client = redis_lib.Redis.from_url(get_settings().redis_url)
    tasks.generate_blueprint.apply(args=[str(job.id)])
    task_db.refresh(job)
    assert calls["n"] == tasks.MAX_RETRIES + 1
    assert job.status == JobStatus.dead and job.error["code"] == "RETRIES_EXHAUSTED"
    dlq = [json.loads(x) for x in client.lrange("specforge:dlq", 0, -1)]
    assert {"job_id": str(job.id), "reason": "retries exhausted"} in dlq


def test_task_missing_job_is_ignored(task_db):
    tasks.generate_blueprint.apply(args=[str(uuid.uuid4())])  # must not raise

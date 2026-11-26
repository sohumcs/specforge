"""Background job submission and progress reporting.

Postgres is the source of truth for job state (it survives Redis flushes and
worker restarts). Redis pub/sub only *pushes* progress to connected browsers;
if a message is lost, the SSE endpoint re-reads the row.

Submission is idempotent in two ways:
* an `Idempotency-Key` header that was seen before returns the original job;
* while a job of the same kind is queued/running for a blueprint, asking again
  returns that job instead of starting a duplicate.
"""

import json
import logging
import uuid
from collections.abc import Callable
from typing import Any

import redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import Conflict, ServiceUnavailable
from app.models import Blueprint, Job, User
from app.models.enums import JobKind, JobStatus

log = logging.getLogger("specforge.jobs")

ACTIVE = (JobStatus.queued, JobStatus.running)
MUTATING = (JobKind.generate, JobKind.fix_issue, JobKind.regenerate_subgraph)
TERMINAL = (JobStatus.succeeded, JobStatus.failed, JobStatus.dead)
CHANNEL = "specforge:jobs:{}"
DLQ_KEY = "specforge:dlq"

Enqueue = Callable[[Job], None]


def redis_client() -> "redis.Redis":
    return redis.Redis.from_url(
        get_settings().redis_url, socket_timeout=2, socket_connect_timeout=2
    )


def find_existing(
    db: Session,
    blueprint: Blueprint,
    kind: JobKind,
    idempotency_key: str | None,
    params: dict[str, Any] | None = None,
) -> Job | None:
    """Return the job this request should reuse, or None to start a new one.

    Graph-mutating jobs (generate, fix, regenerate) are serialised per blueprint:
    an active one with the same params is reused, a different one is a 409."""
    if idempotency_key:
        job = db.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
        if job is not None:
            if job.blueprint_id != blueprint.id or job.kind != kind:
                raise Conflict(
                    "Idempotency-Key was already used for a different request",
                    code="IDEMPOTENCY_KEY_REUSED",
                )
            return job
    active = db.scalars(
        select(Job)
        .where(Job.blueprint_id == blueprint.id, Job.status.in_(ACTIVE))
        .order_by(Job.created_at.desc())
    ).all()
    for job in active:
        if job.kind == kind and (params is None or job.params == params):
            return job
    if kind != JobKind.verify and any(j.kind in MUTATING for j in active):
        raise Conflict(
            "Another change to this blueprint is in progress; try again shortly",
            code="JOB_IN_PROGRESS",
        )
    return None


def create_job(
    db: Session,
    blueprint: Blueprint,
    user: User,
    kind: JobKind,
    *,
    idempotency_key: str | None,
    params: dict[str, Any],
    enqueue: Enqueue,
) -> Job:
    job = Job(
        id=uuid.uuid4(),
        blueprint_id=blueprint.id,
        user_id=user.id,
        kind=kind,
        idempotency_key=idempotency_key,
        params=params,
    )
    db.add(job)
    db.commit()
    try:
        enqueue(job)
    except Exception as exc:
        log.error("enqueue failed for job %s: %s", job.id, exc)
        job.status = JobStatus.failed
        job.error = {"code": "QUEUE_UNAVAILABLE", "message": "Job queue is unavailable"}
        db.commit()
        raise ServiceUnavailable(
            "The job queue is unavailable, please retry shortly", code="QUEUE_UNAVAILABLE"
        ) from exc
    return job


def job_event(job: Job) -> dict[str, Any]:
    return {
        "job_id": str(job.id),
        "blueprint_id": str(job.blueprint_id),
        "kind": job.kind.value,
        "status": job.status.value,
        "step": job.step,
        "progress": job.progress,
        "result": job.result,
        "error": job.error,
    }


def publish(job: Job) -> None:
    try:
        redis_client().publish(CHANNEL.format(job.id), json.dumps(job_event(job), default=str))
    except redis.RedisError:
        log.warning("progress publish failed for job %s (DB still updated)", job.id)


def report_progress(
    db: Session, job: Job, step: str, progress: int, extra: dict[str, Any] | None = None
) -> None:
    job.step = step
    job.progress = max(job.progress, progress)
    if extra:
        job.result = {**(job.result or {}), **extra}
    db.commit()
    publish(job)


def dead_letter(job: Job, reason: str) -> None:
    try:
        redis_client().lpush(DLQ_KEY, json.dumps({"job_id": str(job.id), "reason": reason}))
    except redis.RedisError:
        log.error("could not push job %s to DLQ", job.id)

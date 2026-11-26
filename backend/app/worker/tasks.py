"""Celery tasks. Each task is a thin shell: load the Job row, run a service
function, record the outcome. All business logic lives in app/services."""

import contextlib
import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from prometheus_client import Histogram
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, get_engine
from app.models import Blueprint, Job
from app.models.enums import BlueprintStatus, JobStatus
from app.services import jobs as job_service
from app.services.generation import run_generation
from app.worker.celery_app import celery_app

log = logging.getLogger("specforge.tasks")

JOB_SECONDS = Histogram(
    "specforge_job_duration_seconds",
    "Job duration",
    ["kind", "status"],
    buckets=(1, 5, 10, 20, 40, 60, 120, 300),
)
MAX_RETRIES = 3
TRANSIENT = (OperationalError,)  # DB blips: retry with backoff


def _session() -> Session:
    get_engine()
    return SessionLocal()


# Tests swap this for a factory bound to their transaction.
session_factory: Callable[[], Session] = _session


def _finish(
    db: Session,
    job: Job,
    status: JobStatus,
    *,
    error: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    job.status = status
    if error is not None:
        job.error = error
    if result is not None:
        job.result = {**(job.result or {}), **result}
    if status == JobStatus.succeeded:
        job.step, job.progress = "done", 100
    db.commit()
    job_service.publish(job)


@celery_app.task(bind=True, name="specforge.generate_blueprint", max_retries=MAX_RETRIES)
def generate_blueprint(self: Task, job_id: str) -> None:
    db = session_factory()
    started = time.monotonic()
    try:
        job = db.get(Job, uuid.UUID(job_id))
        if job is None or job.status in job_service.TERMINAL:
            return  # idempotent: duplicate delivery of a finished job is a no-op
        blueprint = db.get(Blueprint, job.blueprint_id)
        if blueprint is None:
            _finish(
                db,
                job,
                JobStatus.failed,
                error={"code": "BLUEPRINT_GONE", "message": "Blueprint was deleted"},
            )
            return
        # A job found "running" was interrupted (worker died) and redelivered:
        # generation is idempotent (replace_graph), so we simply run it again.
        job.status = JobStatus.running
        job.attempts += 1
        db.commit()
        job_service.publish(job)

        def report(step: str, pct: int, extra: dict[str, Any]) -> None:
            job_service.report_progress(db, job, step, pct, extra)

        try:
            summary = run_generation(db, blueprint, report, force=bool(job.params.get("force")))
        except SoftTimeLimitExceeded:
            db.rollback()
            blueprint.status = BlueprintStatus.failed
            _finish(
                db,
                job,
                JobStatus.failed,
                error={"code": "TIMEOUT", "message": "Generation took too long"},
            )
            return
        except TRANSIENT as exc:
            db.rollback()
            if self.request.retries < MAX_RETRIES:
                job.status = JobStatus.queued
                db.commit()
                raise self.retry(exc=exc, countdown=5 * 2**self.request.retries) from exc
            blueprint.status = BlueprintStatus.failed
            _finish(
                db,
                job,
                JobStatus.dead,
                error={"code": "RETRIES_EXHAUSTED", "message": "Job failed repeatedly"},
            )
            job_service.dead_letter(job, "retries exhausted")
            return
        except Exception:
            log.exception("job %s failed", job_id)
            db.rollback()
            blueprint.status = BlueprintStatus.failed
            _finish(
                db,
                job,
                JobStatus.failed,
                error={"code": "GENERATION_FAILED", "message": "Generation failed unexpectedly"},
            )
            return
        _finish(db, job, JobStatus.succeeded, result=summary)
    finally:
        status = "unknown"
        with contextlib.suppress(Exception):  # metrics must never break the task
            j = db.get(Job, uuid.UUID(job_id))
            status = j.status.value if j else "missing"
        JOB_SECONDS.labels("generate", status).observe(time.monotonic() - started)
        db.close()


def enqueue_generation(job: Job) -> None:
    generate_blueprint.apply_async(args=[str(job.id)], task_id=str(job.id), retry=False)

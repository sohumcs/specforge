"""Celery tasks. Each task is a thin shell around a service function; the shared
`_run_job` handles the job lifecycle the same way for every kind:

    load Job -> skip if already finished (duplicate delivery) -> running
    -> work(db, job, blueprint, report) -> succeeded
    on SoftTimeLimitExceeded -> failed (TIMEOUT)
    on transient DB errors   -> retry with exponential backoff, then dead-letter
    on AppError              -> failed with its user-facing code/message
    on anything else         -> failed with a safe, generic error (no internals)
"""

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

from app.core.errors import AppError
from app.db.session import SessionLocal, get_engine
from app.models import Blueprint, Issue, Job
from app.models.enums import BlueprintStatus, JobKind, JobStatus
from app.services import jobs as job_service
from app.services.fixes import apply_fix, regenerate_subgraph
from app.services.generation import run_generation
from app.services.verification import run_verification
from app.worker.celery_app import celery_app

log = logging.getLogger("specforge.tasks")

JOB_SECONDS = Histogram(
    "specforge_job_duration_seconds",
    "Job duration",
    ["kind", "status"],
    buckets=(1, 5, 10, 20, 40, 60, 120, 300),
)
MAX_RETRIES = 3
TRANSIENT = (OperationalError,)

Report = Callable[[str, int, dict[str, Any]], None]
Work = Callable[[Session, Job, Blueprint, Report], dict[str, Any]]


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


def _run_job(task: Task, job_id: str, work: Work, *, marks_blueprint: bool) -> None:
    db = session_factory()
    started = time.monotonic()
    kind = "unknown"
    try:
        job = db.get(Job, uuid.UUID(job_id))
        if job is None or job.status in job_service.TERMINAL:
            return  # idempotent: duplicate delivery of a finished job is a no-op
        kind = job.kind.value
        blueprint = db.get(Blueprint, job.blueprint_id)
        if blueprint is None:
            _finish(
                db,
                job,
                JobStatus.failed,
                error={"code": "BLUEPRINT_GONE", "message": "Blueprint was deleted"},
            )
            return
        # A job found "running" was interrupted (worker died) and redelivered.
        # All work functions are idempotent, so it is simply run again.
        job.status = JobStatus.running
        job.attempts += 1
        db.commit()
        job_service.publish(job)

        def report(step: str, pct: int, extra: dict[str, Any]) -> None:
            job_service.report_progress(db, job, step, pct, extra)

        def fail(code: str, message: str, status: JobStatus = JobStatus.failed) -> None:
            db.rollback()
            if marks_blueprint:
                blueprint.status = BlueprintStatus.failed
            _finish(db, job, status, error={"code": code, "message": message})

        try:
            summary = work(db, job, blueprint, report)
        except SoftTimeLimitExceeded:
            fail("TIMEOUT", "The job took too long")
            return
        except TRANSIENT as exc:
            db.rollback()
            if task.request.retries < MAX_RETRIES:
                job.status = JobStatus.queued
                db.commit()
                raise task.retry(exc=exc, countdown=5 * 2**task.request.retries) from exc
            fail("RETRIES_EXHAUSTED", "The job failed repeatedly", JobStatus.dead)
            job_service.dead_letter(job, "retries exhausted")
            return
        except AppError as exc:  # expected and user-facing (e.g. FIX_NOT_POSSIBLE)
            db.rollback()
            _finish(db, job, JobStatus.failed, error={"code": exc.code, "message": exc.message})
            return
        except Exception:
            log.exception("job %s failed", job_id)
            fail("JOB_FAILED", "The job failed unexpectedly")
            return
        _finish(db, job, JobStatus.succeeded, result=summary)
    finally:
        status = "unknown"
        with contextlib.suppress(Exception):  # metrics must never break the task
            j = db.get(Job, uuid.UUID(job_id))
            status = j.status.value if j else "missing"
        JOB_SECONDS.labels(kind, status).observe(time.monotonic() - started)
        db.close()


# ------------------------------------------------------------------ work functions


def _generate(db: Session, job: Job, bp: Blueprint, report: Report) -> dict[str, Any]:
    summary = run_generation(db, bp, report, force=bool(job.params.get("force")))
    summary["quality"] = run_verification(db, bp, report)
    return summary


def _verify(db: Session, job: Job, bp: Blueprint, report: Report) -> dict[str, Any]:
    return run_verification(db, bp, report)


def _fix(db: Session, job: Job, bp: Blueprint, report: Report) -> dict[str, Any]:
    issue = db.get(Issue, uuid.UUID(job.params["issue_id"]))
    if issue is None:
        raise AppError("Issue no longer exists", code="ISSUE_GONE", status_code=404)
    return apply_fix(db, issue, report)


def _regenerate(db: Session, job: Job, bp: Blueprint, report: Report) -> dict[str, Any]:
    return regenerate_subgraph(db, bp, uuid.UUID(job.params["root_node_id"]), report)


# ------------------------------------------------------------------ tasks


@celery_app.task(bind=True, name="specforge.generate_blueprint", max_retries=MAX_RETRIES)
def generate_blueprint(self: Task, job_id: str) -> None:
    _run_job(self, job_id, _generate, marks_blueprint=True)


@celery_app.task(bind=True, name="specforge.verify_blueprint", max_retries=MAX_RETRIES)
def verify_blueprint(self: Task, job_id: str) -> None:
    _run_job(self, job_id, _verify, marks_blueprint=False)


@celery_app.task(bind=True, name="specforge.fix_issue", max_retries=MAX_RETRIES)
def fix_issue(self: Task, job_id: str) -> None:
    _run_job(self, job_id, _fix, marks_blueprint=False)


@celery_app.task(bind=True, name="specforge.regenerate_subgraph", max_retries=MAX_RETRIES)
def regenerate_subgraph_task(self: Task, job_id: str) -> None:
    _run_job(self, job_id, _regenerate, marks_blueprint=False)


TASKS: dict[JobKind, Task] = {
    JobKind.generate: generate_blueprint,
    JobKind.verify: verify_blueprint,
    JobKind.fix_issue: fix_issue,
    JobKind.regenerate_subgraph: regenerate_subgraph_task,
}


def enqueue(job: Job) -> None:
    TASKS[job.kind].apply_async(args=[str(job.id)], task_id=str(job.id), retry=False)


enqueue_generation = enqueue  # name used by the jobs router

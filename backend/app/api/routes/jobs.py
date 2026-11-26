"""Generation jobs: submit, inspect, and stream progress via Server-Sent Events."""

import asyncio
import contextlib
import json
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Annotated, Any

import redis
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.core.config import get_settings
from app.core.errors import NotFound
from app.db.session import SessionLocal, get_engine
from app.models import Job
from app.models.enums import JobKind, Role
from app.services import jobs as job_service
from app.services import ratelimit
from app.services.access import authorize_blueprint

router = APIRouter(tags=["jobs"])


class GenerateIn(BaseModel):
    force: bool = False  # bypass the generation cache


class JobOut(BaseModel):
    job_id: str
    blueprint_id: str
    kind: str
    status: str
    step: str
    progress: int
    result: dict[str, Any] | None
    error: dict[str, Any] | None


def get_enqueuer() -> job_service.Enqueue:
    from app.worker.tasks import enqueue

    return enqueue


def client_ip(request: Request) -> str:
    # Behind Traefik, uvicorn runs with --proxy-headers so this is the real client.
    return request.client.host if request.client else "unknown"


@router.post(
    "/blueprints/{blueprint_id}/generate",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        200: {"description": "An identical or still-running job already exists"},
        429: {"description": "Rate limit reached"},
    },
)
def generate(
    blueprint_id: uuid.UUID,
    request: Request,
    db: DB,
    user: CurrentUser,
    enqueue: Annotated[job_service.Enqueue, Depends(get_enqueuer)],
    body: GenerateIn | None = None,
    idempotency_key: Annotated[str | None, Header(max_length=100)] = None,
) -> Any:
    bp = authorize_blueprint(db, user, blueprint_id, Role.editor)
    return submit_job(
        db,
        user,
        request,
        bp,
        JobKind.generate,
        {"force": bool(body and body.force)},
        idempotency_key,
        enqueue,
    )


def submit_job(
    db: DB,
    user: CurrentUser,
    request: Request,
    bp: Any,
    kind: JobKind,
    params: dict[str, Any],
    idempotency_key: str | None,
    enqueue: job_service.Enqueue,
) -> Any:
    """Shared submission path: idempotency -> rate limit -> create + enqueue.
    Returns 200 with an existing job, or 202 with a new one."""
    existing = job_service.find_existing(db, bp, kind, idempotency_key, params)
    if existing is not None:
        return JSONResponse(job_service.job_event(existing), status_code=200)
    ip = client_ip(request)
    if kind == JobKind.verify:  # CPU only, no LLM quota: a looser per-IP limit
        limits = [ratelimit.Limit("ip", ip, get_settings().verify_limit_per_ip_hour, 3600)]
    else:
        limits = ratelimit.generation_limits(str(user.id), user.is_demo, ip)
    ratelimit.check(limits, action="verify" if kind == JobKind.verify else "llm")
    job = job_service.create_job(
        db, bp, user, kind, idempotency_key=idempotency_key, params=params, enqueue=enqueue
    )
    return job_service.job_event(job)


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, db: DB, user: CurrentUser) -> Any:
    job = db.get(Job, job_id)
    if job is None:
        raise NotFound("Job not found")
    authorize_blueprint(db, user, job.blueprint_id, Role.viewer)
    return job_service.job_event(job)


@router.get("/blueprints/{blueprint_id}/jobs", response_model=list[JobOut])
def list_jobs(blueprint_id: uuid.UUID, db: DB, user: CurrentUser) -> Any:
    authorize_blueprint(db, user, blueprint_id, Role.viewer)
    rows = db.scalars(
        select(Job)
        .where(Job.blueprint_id == blueprint_id)
        .order_by(Job.created_at.desc())
        .limit(20)
    )
    return [job_service.job_event(j) for j in rows]


# ------------------------------------------------------------------------ SSE


def _read_job(job_id: uuid.UUID) -> dict[str, Any] | None:
    """Fresh short-lived session: a streaming response outlives request deps."""
    get_engine()
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        return job_service.job_event(job) if job else None


# Tests replace this to read from their transaction.
read_job: Callable[[uuid.UUID], dict[str, Any] | None] = _read_job

TERMINAL_VALUES = {s.value for s in job_service.TERMINAL}
HEARTBEAT_SECONDS = 15.0
RESYNC_SECONDS = 5.0
MAX_STREAM_SECONDS = 600.0


def _sse(event: dict[str, Any], name: str = "progress") -> str:
    return f"event: {name}\ndata: {json.dumps(event, default=str)}\n\n"


async def job_stream(job_id: uuid.UUID) -> AsyncIterator[str]:
    """Push events from Redis pub/sub; re-read the DB periodically so a missed
    message (or a Redis outage) never leaves the client stuck."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + MAX_STREAM_SECONDS
    last: dict[str, Any] | None = await run_in_threadpool(read_job, job_id)
    if last is None:
        yield _sse({"message": "job not found"}, "error")
        return
    yield _sse(last)
    if last["status"] in TERMINAL_VALUES:
        return

    pubsub = None
    try:
        client = aioredis.from_url(get_settings().redis_url, socket_connect_timeout=2)
        pubsub = client.pubsub()
        await pubsub.subscribe(job_service.CHANNEL.format(job_id))
    except (redis.RedisError, OSError):
        pubsub = None  # degrade to DB polling

    next_resync = loop.time() + RESYNC_SECONDS
    next_heartbeat = loop.time() + HEARTBEAT_SECONDS
    try:
        while loop.time() < deadline:
            event = None
            if pubsub is not None:
                try:
                    msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if msg and msg.get("type") == "message":
                        event = json.loads(msg["data"])
                except (redis.RedisError, OSError):
                    pubsub = None
            else:
                await asyncio.sleep(1.0)
                next_resync = 0  # poll every second without Redis
            now = loop.time()
            if event is None and now >= next_resync:
                event = await run_in_threadpool(read_job, job_id)
                next_resync = now + RESYNC_SECONDS
            if event is not None and event != last:
                last = event
                next_heartbeat = now + HEARTBEAT_SECONDS
                yield _sse(event)
                if event["status"] in TERMINAL_VALUES:
                    return
            elif now >= next_heartbeat:
                next_heartbeat = now + HEARTBEAT_SECONDS
                yield ": keep-alive\n\n"
    finally:
        if pubsub is not None:
            with contextlib.suppress(redis.RedisError, OSError):
                await pubsub.aclose()


@router.get(
    "/jobs/{job_id}/events",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
def job_events(job_id: uuid.UUID, db: DB, user: CurrentUser) -> StreamingResponse:
    job = db.get(Job, job_id)
    if job is None:
        raise NotFound("Job not found")
    authorize_blueprint(db, user, job.blueprint_id, Role.viewer)
    return StreamingResponse(
        job_stream(job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

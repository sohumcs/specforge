"""Probes and status.

/health  - liveness: the process is up. No dependencies, so a slow DB never
           causes Kubernetes to restart healthy API pods.
/ready   - readiness: DB and Redis reachable. 503 with details otherwise.
/status  - human-facing component health + version, for the /status page.
"""

import logging
from typing import Any

import redis
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_engine
from app.llm.breaker import RedisBreaker

router = APIRouter(tags=["health"])
log = logging.getLogger("specforge.health")


def check_db() -> dict[str, Any]:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True}
    except Exception as exc:
        log.warning("db check failed: %s", exc)
        return {"ok": False, "error": "database unreachable"}


def check_redis() -> dict[str, Any]:
    try:
        client = redis.Redis.from_url(
            get_settings().redis_url, socket_timeout=1, socket_connect_timeout=1
        )
        client.ping()
        return {"ok": True}
    except Exception as exc:
        log.warning("redis check failed: %s", exc)
        return {"ok": False, "error": "redis unreachable"}


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready() -> JSONResponse:
    checks = {"database": check_db(), "redis": check_redis()}
    ok = all(c["ok"] for c in checks.values())
    body = {"status": "ready" if ok else "not_ready", "checks": checks}
    return JSONResponse(body, status_code=200 if ok else 503)


@router.get("/api/v1/status")
def status() -> dict[str, Any]:
    s = get_settings()
    components = {"api": {"ok": True}, "database": check_db(), "redis": check_redis()}
    breaker = RedisBreaker()
    providers = {
        name: {
            "configured": bool(key.get_secret_value()),
            "model": model,
            "circuit_open_seconds": breaker.remaining(name),
        }
        for name, key, model in (
            ("gemini", s.gemini_api_key, s.gemini_model),
            ("groq", s.groq_api_key, s.groq_model),
        )
    }
    providers["demo"] = {"configured": True, "model": "templates-v1", "circuit_open_seconds": 0}
    return {
        "version": s.app_version,
        "commit": s.git_sha,
        "ci_run_url": s.ci_run_url,
        "environment": s.environment,
        "components": components,
        "llm_providers": providers,
        "llm_chain": [*s.llm_providers, "cache", "demo"],
    }

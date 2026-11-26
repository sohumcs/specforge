"""FastAPI application factory."""

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from app.api.routes import auth, blueprints, health, jobs, projects, quality
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, request_id_var

log = logging.getLogger("specforge.http")

REQUEST_LATENCY = Histogram(
    "specforge_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route", "status"],
)
REQUEST_COUNT = Counter(
    "specforge_http_requests_total", "HTTP requests", ["method", "route", "status"]
)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="SPECForge API",
        version=settings.app_version,
        description="Turn a project brief into a traceable, self-checking software blueprint.",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    register_error_handlers(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("X-Request-ID", "")
        rid = incoming if 0 < len(incoming) <= 64 and incoming.isprintable() else uuid.uuid4().hex
        token = request_id_var.set(rid)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        elapsed = time.perf_counter() - start
        route = request.scope.get("route")
        route_path = getattr(route, "path", "unmatched")
        REQUEST_LATENCY.labels(request.method, route_path, response.status_code).observe(elapsed)
        REQUEST_COUNT.labels(request.method, route_path, response.status_code).inc()
        response.headers["X-Request-ID"] = rid
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if settings.cookie_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        log.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round(elapsed * 1000, 1),
            },
        )
        return response

    api = "/api/v1"
    app.include_router(health.router)
    app.include_router(auth.router, prefix=api)
    app.include_router(auth.me_router, prefix=api)
    app.include_router(projects.router, prefix=api)
    app.include_router(projects.admin_router, prefix=api)
    app.include_router(blueprints.router, prefix=api)
    app.include_router(jobs.router, prefix=api)
    app.include_router(quality.router, prefix=api)

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()

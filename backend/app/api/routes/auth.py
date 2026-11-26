import contextlib
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.deps import DB, CurrentUser
from app.api.routes.jobs import get_enqueuer
from app.core.config import get_settings
from app.core.errors import Unauthorized
from app.models.enums import JobKind
from app.schemas.auth import LoginIn, RegisterIn, TokenOut, UserOut
from app.services import auth_service, ratelimit, samples
from app.services import jobs as job_service
from app.services.auth_service import TokenPair

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_PATH = "/api/v1/auth"


def _respond(response: Response, pair: TokenPair) -> TokenOut:
    """Refresh token goes in an httpOnly cookie scoped to /auth; the access
    token goes in the body and lives only in the SPA's memory."""
    s = get_settings()
    response.set_cookie(
        s.refresh_cookie_name,
        pair.refresh_token,
        max_age=s.refresh_token_days * 86400,
        httponly=True,
        secure=s.cookie_secure,
        samesite="strict",
        path=COOKIE_PATH,
    )
    return TokenOut(access_token=pair.access_token, expires_in=pair.expires_in)


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, db: DB, response: Response) -> TokenOut:
    user = auth_service.register(
        db, email=body.email, password=body.password, display_name=body.display_name
    )
    return _respond(response, auth_service.issue_tokens(db, user))


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: DB, response: Response) -> TokenOut:
    user = auth_service.authenticate(db, email=body.email, password=body.password)
    return _respond(response, auth_service.issue_tokens(db, user))


@router.post("/demo", response_model=TokenOut)
def demo_login(
    request: Request,
    db: DB,
    response: Response,
    enqueue: Annotated[job_service.Enqueue, Depends(get_enqueuer)],
) -> TokenOut:
    """One-click recruiter login: editor on the shared sandbox project."""
    ip = request.client.host if request.client else "unknown"
    ratelimit.check(
        [ratelimit.Limit("ip", ip, get_settings().demo_login_limit_per_ip_hour, 3600)],
        action="demo_login",
    )
    user = auth_service.ensure_demo_user(db)
    for bp in samples.ensure_sandbox_samples(db):  # self-heal an empty sandbox
        with contextlib.suppress(Exception):  # verification is best-effort here
            job_service.create_job(
                db,
                bp,
                user,
                JobKind.verify,
                idempotency_key=None,
                params={},
                enqueue=enqueue,
            )
    return _respond(response, auth_service.issue_tokens(db, user))


@router.post("/refresh", response_model=TokenOut)
def refresh(request: Request, db: DB, response: Response) -> TokenOut:
    raw = request.cookies.get(get_settings().refresh_cookie_name)
    if not raw:
        raise Unauthorized("Missing refresh token", code="REFRESH_MISSING")
    return _respond(response, auth_service.rotate_refresh(db, raw))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, db: DB, response: Response) -> Response:
    s = get_settings()
    raw = request.cookies.get(s.refresh_cookie_name)
    if raw:
        auth_service.revoke(db, raw)
    response.delete_cookie(s.refresh_cookie_name, path=COOKIE_PATH)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


me_router = APIRouter(tags=["auth"])


@me_router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)

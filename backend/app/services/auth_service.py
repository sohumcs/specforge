"""Registration, login and refresh-token rotation with reuse detection.

Refresh rotation: every successful refresh revokes the presented token and
issues a new one in the same *family*. If a token that was already revoked is
presented again, someone replayed a stolen token, so the whole family is revoked
and the user must sign in again.
"""

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import Conflict, Unauthorized
from app.core.security import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from app.models import Project, ProjectMember, RefreshToken, User
from app.models.enums import Role

# Verifying against a dummy hash when the user doesn't exist keeps login timing
# roughly constant, so response time doesn't reveal which emails are registered.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


@dataclass
class TokenPair:
    access_token: str
    expires_in: int
    refresh_token: str


def register(db: Session, *, email: str, password: str, display_name: str) -> User:
    if db.scalar(select(User).where(User.email == email)):
        raise Conflict("An account with this email already exists", code="EMAIL_TAKEN")
    user = User(email=email, password_hash=hash_password(password), display_name=display_name)
    db.add(user)
    db.commit()
    return user


def authenticate(db: Session, *, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user is None or user.is_demo:
        verify_password(password, _DUMMY_HASH)
        raise Unauthorized("Invalid email or password", code="INVALID_CREDENTIALS")
    if not verify_password(password, user.password_hash):
        raise Unauthorized("Invalid email or password", code="INVALID_CREDENTIALS")
    return user


def _add_refresh_row(db: Session, user: User, family_id: uuid.UUID) -> tuple[str, RefreshToken]:
    raw, token_hash = new_refresh_token()
    row = RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        family_id=family_id,
        expires_at=datetime.now(UTC) + timedelta(days=get_settings().refresh_token_days),
    )
    db.add(row)
    db.flush()
    return raw, row


def issue_tokens(db: Session, user: User) -> TokenPair:
    """Start a new refresh-token family (login, register, demo)."""
    access, ttl = create_access_token(user.id, is_admin=user.is_admin)
    raw, _ = _add_refresh_row(db, user, uuid.uuid4())
    db.commit()
    return TokenPair(access_token=access, expires_in=ttl, refresh_token=raw)


def rotate_refresh(db: Session, raw_token: str) -> TokenPair:
    token = db.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_refresh_token(raw_token))
        .with_for_update()
    )
    if token is None:
        raise Unauthorized("Invalid refresh token", code="REFRESH_INVALID")
    now = datetime.now(UTC)
    if token.revoked_at is not None:
        _revoke_family(db, token.family_id, now)
        db.commit()
        raise Unauthorized("Refresh token reuse detected; signed out", code="REFRESH_REUSED")
    if token.expires_at <= now:
        raise Unauthorized("Refresh token expired", code="REFRESH_EXPIRED")

    user = db.get(User, token.user_id)
    if user is None:
        raise Unauthorized("Invalid refresh token", code="REFRESH_INVALID")
    # Revoke the old token and add its replacement in ONE transaction while the
    # row lock is held, so two concurrent refreshes can't both succeed.
    raw, new_row = _add_refresh_row(db, user, token.family_id)
    token.revoked_at = now
    token.replaced_by = new_row.id
    access, ttl = create_access_token(user.id, is_admin=user.is_admin)
    db.commit()
    return TokenPair(access_token=access, expires_in=ttl, refresh_token=raw)


def revoke(db: Session, raw_token: str) -> None:
    token = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_token))
    )
    if token is not None:
        _revoke_family(db, token.family_id, datetime.now(UTC))
        db.commit()


def _revoke_family(db: Session, family_id: uuid.UUID, now: datetime) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )


def ensure_demo_user(db: Session) -> User:
    """Shared demo account: `editor` on the sandbox project, cannot log in by password."""
    settings = get_settings()
    user = db.scalar(select(User).where(User.email == settings.demo_email))
    if user is None:
        user = User(
            email=settings.demo_email,
            display_name="Demo Recruiter",
            password_hash=hash_password(secrets.token_urlsafe(32)),
            is_demo=True,
        )
        db.add(user)
        db.flush()
    sandbox = db.scalar(select(Project).where(Project.is_sandbox.is_(True)))
    if sandbox is None:
        sandbox = Project(
            name=settings.sandbox_project_name,
            description="Shared demo workspace. Resets nightly.",
            is_sandbox=True,
        )
        db.add(sandbox)
        db.flush()
    member = db.get(ProjectMember, (sandbox.id, user.id))
    if member is None:
        db.add(ProjectMember(project_id=sandbox.id, user_id=user.id, role=Role.editor))
    db.commit()
    return user

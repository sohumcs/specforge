"""Password hashing (Argon2id), JWT access tokens and opaque refresh tokens.

Access tokens are short-lived JWTs. Refresh tokens are random opaque strings;
only their SHA-256 hash is stored, so a database leak does not leak sessions.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import get_settings
from app.core.errors import Unauthorized

_hasher = PasswordHasher()  # argon2id with the library's recommended parameters


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def create_access_token(user_id: uuid.UUID, *, is_admin: bool) -> tuple[str, int]:
    """Return (jwt, lifetime_seconds)."""
    settings = get_settings()
    now = datetime.now(UTC)
    ttl = timedelta(minutes=settings.access_token_minutes)
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + ttl,
        "jti": uuid.uuid4().hex,
        "typ": "access",
        "adm": is_admin,
    }
    token = jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, int(ttl.total_seconds())


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub", "typ"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise Unauthorized("Access token expired", code="TOKEN_EXPIRED") from exc
    except jwt.InvalidTokenError as exc:
        raise Unauthorized("Invalid access token", code="TOKEN_INVALID") from exc
    if claims.get("typ") != "access":
        raise Unauthorized("Invalid access token", code="TOKEN_INVALID")
    return claims


def new_refresh_token() -> tuple[str, str]:
    """Return (raw token for the client, sha256 hash for the database)."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()

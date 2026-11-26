"""Fixed-window rate limits in Redis, protecting the free LLM quotas.

`INCR key; EXPIRE key window NX` is atomic per key and survives API restarts.
Limits are checked per user, per client IP and globally per day. The shared
demo account is limited per IP (all recruiters share one user id).

If Redis is down we refuse to generate (503) rather than run unmetered.
"""

import time
from dataclasses import dataclass

import redis

from app.core.config import get_settings
from app.core.errors import AppError, ServiceUnavailable

PREFIX = "specforge:rl:"


@dataclass(frozen=True)
class Limit:
    scope: str  # "user" | "ip" | "global"
    ident: str
    limit: int
    window: int  # seconds


class RateLimited(AppError):
    status_code = 429
    code = "RATE_LIMITED"


def _client() -> "redis.Redis":
    return redis.Redis.from_url(
        get_settings().redis_url, socket_timeout=1, socket_connect_timeout=1
    )


def check(limits: list[Limit], *, action: str, client: "redis.Redis | None" = None) -> None:
    r = client or _client()
    now = int(time.time())
    try:
        pipe = r.pipeline()
        keys = []
        for lim in limits:
            window_start = now - now % lim.window
            key = f"{PREFIX}{action}:{lim.scope}:{lim.ident}:{window_start}"
            keys.append((lim, window_start))
            pipe.incr(key)
            pipe.expire(key, lim.window, nx=True)
        results = pipe.execute()
    except redis.RedisError as exc:
        raise ServiceUnavailable(
            "Rate limiter unavailable, please retry shortly", code="RATE_LIMITER_UNAVAILABLE"
        ) from exc

    for i, (lim, window_start) in enumerate(keys):
        count = int(results[i * 2])
        if count > lim.limit:
            retry_after = window_start + lim.window - now
            friendly = {
                "user": "You've generated a lot of blueprints recently",
                "ip": "This network has generated a lot of blueprints recently",
                "global": "The free demo has reached today's AI generation budget",
            }[lim.scope]
            raise RateLimited(
                f"{friendly}. Try again in {max(retry_after, 1) // 60 + 1} min, "
                "or explore the sample blueprints meanwhile.",
                details={
                    "scope": lim.scope,
                    "limit": lim.limit,
                    "window_seconds": lim.window,
                    "retry_after_seconds": max(retry_after, 1),
                },
            )


def generation_limits(user_id: str, is_demo: bool, ip: str) -> list[Limit]:
    s = get_settings()
    limits = [
        Limit("ip", ip, s.generate_limit_per_ip_hour, 3600),
        Limit("global", "all", s.generate_limit_global_day, 86400),
    ]
    if not is_demo:
        limits.insert(0, Limit("user", user_id, s.generate_limit_per_user_hour, 3600))
    return limits

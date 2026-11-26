"""Per-provider circuit breaker stored in Redis.

After a quota/rate-limit/5xx failure the provider is skipped for a cool-down
period (at least the provider's own Retry-After), so we don't spend every job's
time budget hitting a provider we already know is down. Shared via Redis, so
all workers see the same state.

If Redis itself is unavailable the breaker fails *open* (closed circuit): we'd
rather try the provider than refuse to generate.
"""

import logging
import time
from typing import Protocol

import redis

from app.core.config import get_settings

log = logging.getLogger("specforge.llm.breaker")
PREFIX = "specforge:llm:breaker:"


class Breaker(Protocol):
    def is_open(self, provider: str) -> bool: ...
    def trip(self, provider: str, seconds: float) -> None: ...


class RedisBreaker:
    def __init__(self, client: "redis.Redis | None" = None) -> None:
        self.client = client or redis.Redis.from_url(
            get_settings().redis_url, socket_timeout=1, socket_connect_timeout=1
        )

    def is_open(self, provider: str) -> bool:
        try:
            return bool(self.client.exists(PREFIX + provider))
        except redis.RedisError:
            log.warning("breaker unavailable; assuming closed for %s", provider)
            return False

    def trip(self, provider: str, seconds: float) -> None:
        try:
            self.client.set(PREFIX + provider, "1", ex=max(1, int(seconds)))
            log.warning("circuit opened for %s for %ss", provider, int(seconds))
        except redis.RedisError:
            log.warning("could not record breaker for %s", provider)

    def remaining(self, provider: str) -> int:
        try:
            ttl = int(self.client.ttl(PREFIX + provider))
            return max(ttl, 0)
        except redis.RedisError:
            return 0


class MemoryBreaker:
    """In-process breaker for tests and single-process dev."""

    def __init__(self) -> None:
        self.until: dict[str, float] = {}

    def is_open(self, provider: str) -> bool:
        return self.until.get(provider, 0) > time.monotonic()

    def trip(self, provider: str, seconds: float) -> None:
        self.until[provider] = time.monotonic() + seconds

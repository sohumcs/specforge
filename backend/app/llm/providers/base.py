"""The provider contract.

A provider turns an `LLMRequest` into a JSON object (as a Python dict). It does
not validate meaning; `app.llm.chain` validates with Pydantic, asks for repairs,
and falls back to the next provider.

Errors are classified so the chain can react correctly:
* ProviderUnavailable - quota, rate limit, 5xx, timeout: try the next provider,
  and open this provider's circuit breaker for a while.
* ProviderBadOutput   - the reply wasn't JSON: worth a repair retry.
* ProviderConfigError - misconfigured (e.g. 400/401/403): skip this provider.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


@dataclass
class LLMRequest:
    stage: str  # "requirements" | "design" | "tests"
    system: str
    prompt: str
    json_schema: dict[str, Any]
    schema_name: str
    # Structured context for providers that don't read prompts (DemoProvider).
    context: dict[str, Any] = field(default_factory=dict)
    history: list[tuple[str, str]] = field(default_factory=list)  # (assistant, user) repair turns


@dataclass
class LLMResponse:
    data: dict[str, Any]
    provider: str
    model: str
    usage: dict[str, Any] = field(default_factory=dict)


class ProviderError(Exception):
    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ProviderUnavailable(ProviderError):
    pass


class ProviderBadOutput(ProviderError):
    def __init__(self, message: str, raw: str = "") -> None:
        super().__init__(message)
        self.raw = raw


class ProviderConfigError(ProviderError):
    pass


class LLMProvider(Protocol):
    name: str

    def configured(self) -> bool: ...

    def complete_json(self, request: LLMRequest) -> LLMResponse: ...


def classify_http_error(provider: str, resp: httpx.Response) -> ProviderError:
    """Map an HTTP failure to the right error class (no response body in the
    message: it can echo our prompt and is noisy in logs)."""
    retry_after: float | None = None
    header = resp.headers.get("retry-after")
    if header:
        try:
            retry_after = float(header)
        except ValueError:
            retry_after = None
    code = resp.status_code
    if code == 429 or code >= 500:
        return ProviderUnavailable(f"{provider} unavailable (HTTP {code})", retry_after=retry_after)
    if code in (400, 401, 403, 404):
        return ProviderConfigError(f"{provider} rejected the request (HTTP {code})")
    return ProviderUnavailable(f"{provider} error (HTTP {code})")

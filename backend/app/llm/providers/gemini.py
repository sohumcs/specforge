"""Google Gemini adapter (REST `generateContent` with a JSON response schema)."""

import json
from typing import Any

import httpx

from app.core.config import get_settings
from app.llm.providers.base import (
    LLMRequest,
    LLMResponse,
    ProviderBadOutput,
    ProviderUnavailable,
    classify_http_error,
)

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


def _retry_delay(resp: httpx.Response) -> float | None:
    """Gemini puts the wait in the error body (google.rpc.RetryInfo), e.g. "13s"."""
    try:
        details = resp.json()["error"]["details"]
    except (ValueError, KeyError, TypeError):
        return None
    for d in details if isinstance(details, list) else []:
        delay = d.get("retryDelay") if isinstance(d, dict) else None
        if isinstance(delay, str) and delay.endswith("s"):
            try:
                return float(delay[:-1])
            except ValueError:
                return None
    return None


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        s = get_settings()
        self.api_key = api_key if api_key is not None else s.gemini_api_key.get_secret_value()
        self.model = model or s.gemini_model
        self.client = client or httpx.Client(timeout=s.llm_timeout_seconds)

    def configured(self) -> bool:
        return bool(self.api_key)

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        contents: list[dict[str, Any]] = [{"role": "user", "parts": [{"text": request.prompt}]}]
        for assistant, user in request.history:
            contents.append({"role": "model", "parts": [{"text": assistant}]})
            contents.append({"role": "user", "parts": [{"text": user}]})
        body = {
            "systemInstruction": {"parts": [{"text": request.system}]},
            "contents": contents,
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": request.json_schema,
                "temperature": 0.3,
            },
        }
        try:
            resp = self.client.post(
                f"{BASE_URL}/models/{self.model}:generateContent",
                headers={"x-goog-api-key": self.api_key},
                json=body,
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"gemini transport error: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            err = classify_http_error(self.name, resp)
            if err.retry_after is None:
                err.retry_after = _retry_delay(resp)
            raise err

        payload = resp.json()
        try:
            candidate = payload["candidates"][0]
            text = "".join(p.get("text", "") for p in candidate["content"]["parts"])
        except (KeyError, IndexError, TypeError) as exc:
            # Safety blocks / empty candidates come back as 200 without content.
            raise ProviderBadOutput("gemini returned no content") from exc
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderBadOutput(f"gemini returned invalid JSON: {exc.msg}", raw=text) from exc
        if not isinstance(data, dict):
            raise ProviderBadOutput("gemini returned JSON that is not an object", raw=text)
        return LLMResponse(
            data=data,
            provider=self.name,
            model=self.model,
            usage=payload.get("usageMetadata", {}),
        )

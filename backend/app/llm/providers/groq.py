"""Groq adapter (OpenAI-compatible chat completions with strict json_schema).

Free plan: 8K tokens/minute and 1K requests/day per model (checked via the
x-ratelimit-* response headers on 2026-11-26). gpt-oss is a reasoning model and
reasoning tokens count, so we ask for low reasoning effort.
"""

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

BASE_URL = "https://api.groq.com/openai/v1"


class GroqProvider:
    name = "groq"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        s = get_settings()
        self.api_key = api_key if api_key is not None else s.groq_api_key.get_secret_value()
        self.model = model or s.groq_model
        self.client = client or httpx.Client(timeout=s.llm_timeout_seconds)

    def configured(self) -> bool:
        return bool(self.api_key)

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": request.system},
            {"role": "user", "content": request.prompt},
        ]
        for assistant, user in request.history:
            messages += [
                {"role": "assistant", "content": assistant},
                {"role": "user", "content": user},
            ]
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.3,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": request.schema_name,
                    "strict": True,
                    "schema": request.json_schema,
                },
            },
        }
        if self.model.startswith("openai/gpt-oss"):
            body["reasoning_effort"] = "low"
        try:
            resp = self.client.post(
                f"{BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=body,
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"groq transport error: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            err = classify_http_error(self.name, resp)
            # Groq reports schema-validation failures of its own output as 400 json_validate_failed.
            if resp.status_code == 400 and "json_validate_failed" in resp.text:
                raise ProviderBadOutput("groq output failed schema validation")
            raise err

        payload = resp.json()
        try:
            text = payload["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderBadOutput("groq returned no content") from exc
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderBadOutput(f"groq returned invalid JSON: {exc.msg}", raw=text) from exc
        if not isinstance(data, dict):
            raise ProviderBadOutput("groq returned JSON that is not an object", raw=text)
        return LLMResponse(
            data=data, provider=self.name, model=self.model, usage=payload.get("usage", {})
        )

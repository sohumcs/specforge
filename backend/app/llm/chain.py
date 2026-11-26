"""Fallback chain + structured-output validation with repair retries.

    for each stage (requirements -> design -> tests):
        for provider in [gemini, groq, ...]:          skip if unconfigured / circuit open
            ask for JSON matching the stage schema
            validate: Pydantic shape + cross-reference check
            invalid?  -> send the errors back ("repair"), up to N retries
            429/5xx?  -> wait if Retry-After is short, else trip breaker, next provider
    any stage exhausted every provider?
        -> cached blueprint for the same brief (older prompt version), if any
        -> DemoProvider for the WHOLE blueprint (stages must stay consistent)

The result records which provider produced each stage; the UI shows it as a badge.
"""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from prometheus_client import Counter
from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.llm import prompts
from app.llm.breaker import Breaker
from app.llm.jsonschema import strict_schema
from app.llm.providers.base import (
    LLMProvider,
    LLMRequest,
    ProviderBadOutput,
    ProviderConfigError,
    ProviderUnavailable,
)
from app.llm.providers.demo import DemoProvider
from app.llm.schemas import (
    BlueprintDraft,
    DesignDraft,
    RequirementsDraft,
    TestsDraft,
    cross_reference_errors,
)
from app.nlp.brief import BriefSignals

log = logging.getLogger("specforge.llm")

LLM_CALLS = Counter(
    "specforge_llm_calls_total",
    "LLM calls by provider/stage/outcome",
    ["provider", "stage", "outcome"],
)
LLM_FALLBACKS = Counter("specforge_llm_fallbacks_total", "Generations that fell back", ["to"])

M = TypeVar("M", bound=BaseModel)
Progress = Callable[[str, int], None]

# Size targets per stage, rendered into the prompts.
SIZES = {
    "req_min": 6,
    "req_max": 10,
    "story_min": 8,
    "story_max": 14,
    "mod_min": 4,
    "mod_max": 7,
    "ent_min": 4,
    "ent_max": 8,
    "api_min": 10,
    "api_max": 18,
    "test_min": 8,
    "test_max": 14,
}


class AllProvidersFailed(Exception):
    def __init__(self, stage: str, attempts: list[dict[str, str]]) -> None:
        super().__init__(f"every provider failed for stage '{stage}'")
        self.stage = stage
        self.attempts = attempts


@dataclass
class StageResult:
    model: BaseModel
    provider: str
    model_name: str
    repairs: int


@dataclass
class GenerationResult:
    draft: BlueprintDraft
    provider: str  # badge text, e.g. "gemini", "gemini+groq", "cache", "demo"
    stage_providers: dict[str, str] = field(default_factory=dict)
    attempts: list[dict[str, str]] = field(default_factory=list)


def _format_validation(exc: ValidationError) -> list[str]:
    out = []
    for e in exc.errors()[:20]:
        loc = ".".join(str(p) for p in e["loc"])
        out.append(f"{loc}: {e['msg']}")
    return out


def run_stage[M: BaseModel](
    *,
    stage: str,
    schema: type[M],
    prompt: str,
    context: dict[str, Any],
    providers: list[LLMProvider],
    breaker: Breaker,
    extra_checks: Callable[[M], list[str]],
    sleep: Callable[[float], None] = time.sleep,
) -> StageResult:
    s = get_settings()
    system = prompts.render("system")
    json_schema = strict_schema(schema)
    attempts: list[dict[str, str]] = []

    for provider in providers:
        if not provider.configured():
            continue
        if breaker.is_open(provider.name):
            attempts.append({"provider": provider.name, "outcome": "circuit_open"})
            continue
        request = LLMRequest(
            stage=stage,
            system=system,
            prompt=prompt,
            json_schema=json_schema,
            schema_name=schema.__name__,
            context=context,
        )
        waited = False
        repairs = 0
        while repairs <= s.llm_repair_retries:
            try:
                response = provider.complete_json(request)
            except ProviderUnavailable as exc:
                if (
                    exc.retry_after is not None
                    and exc.retry_after <= s.llm_max_wait_seconds
                    and not waited
                ):
                    waited = True  # short rate-limit window: wait once, then retry
                    LLM_CALLS.labels(provider.name, stage, "rate_limited_wait").inc()
                    sleep(exc.retry_after)
                    continue
                LLM_CALLS.labels(provider.name, stage, "unavailable").inc()
                breaker.trip(provider.name, max(exc.retry_after or 0, s.llm_breaker_seconds))
                attempts.append(
                    {"provider": provider.name, "outcome": "unavailable", "detail": str(exc)}
                )
                break
            except ProviderConfigError as exc:
                LLM_CALLS.labels(provider.name, stage, "config_error").inc()
                attempts.append(
                    {"provider": provider.name, "outcome": "config_error", "detail": str(exc)}
                )
                break
            except ProviderBadOutput as exc:
                problems, raw = [str(exc)], exc.raw
            else:
                raw = json.dumps(response.data, separators=(",", ":"))
                try:
                    parsed = schema.model_validate(response.data)
                    problems = extra_checks(parsed)
                except ValidationError as exc:
                    problems = _format_validation(exc)
                if not problems:
                    LLM_CALLS.labels(provider.name, stage, "ok").inc()
                    log.info("stage %s ok via %s after %d repairs", stage, provider.name, repairs)
                    return StageResult(parsed, provider.name, response.model, repairs)

            LLM_CALLS.labels(provider.name, stage, "invalid").inc()
            repairs += 1
            log.info(
                "stage %s: %s output invalid (%d problems), repair %d",
                stage,
                provider.name,
                len(problems),
                repairs,
            )
            bullet_list = "\n".join(f"- {p}" for p in problems[:15])
            request.history.append((raw or "{}", prompts.render("repair", errors=bullet_list)))
        else:
            attempts.append({"provider": provider.name, "outcome": "invalid_after_repairs"})
    raise AllProvidersFailed(stage, attempts)


def _compact_stage_a(a: RequirementsDraft) -> str:
    return json.dumps(
        {
            "requirements": [
                {"ref": r.ref, "kind": r.kind, "title": r.title} for r in a.requirements
            ],
            "stories": [
                {"ref": s.ref, "title": s.title, "requirement_refs": s.requirement_refs}
                for s in a.stories
            ],
        },
        separators=(",", ":"),
    )


def _compact_stories(a: RequirementsDraft) -> str:
    return json.dumps(
        [
            {"ref": s.ref, "title": s.title, "acceptance_criteria": s.acceptance_criteria}
            for s in a.stories
        ],
        separators=(",", ":"),
    )


def _compact_apis(b: DesignDraft) -> str:
    return json.dumps(
        [{"ref": x.ref, "endpoint": f"{x.method} {x.path}", "summary": x.summary} for x in b.apis],
        separators=(",", ":"),
    )


def generate_draft(
    brief: str,
    signals: BriefSignals,
    *,
    providers: list[LLMProvider],
    breaker: Breaker,
    progress: Progress = lambda step, pct: None,
    stale_cache: Callable[[], BlueprintDraft | None] = lambda: None,
    sleep: Callable[[float], None] = time.sleep,
) -> GenerationResult:
    ctx = {"brief": brief}
    common: dict[str, Any] = {
        "providers": providers,
        "breaker": breaker,
        "context": ctx,
        "sleep": sleep,
    }
    try:
        progress("generating_requirements", 15)
        a = run_stage(
            stage="requirements",
            schema=RequirementsDraft,
            prompt=prompts.render(
                "requirements",
                brief=brief,
                actors=", ".join(signals.actors) or "(none found)",
                entities=", ".join(signals.entities) or "(none found)",
                terms=", ".join(signals.terms) or "(none found)",
                **SIZES,
            ),
            extra_checks=lambda m: cross_reference_errors(a=m),
            **common,
        )
        ra: RequirementsDraft = a.model  # type: ignore[assignment]

        progress("generating_design", 40)
        b = run_stage(
            stage="design",
            schema=DesignDraft,
            prompt=prompts.render("design", brief=brief, stage_a=_compact_stage_a(ra), **SIZES),
            extra_checks=lambda m: cross_reference_errors(a=ra, b=m),
            **common,
        )
        rb: DesignDraft = b.model  # type: ignore[assignment]

        progress("generating_tests", 65)
        c = run_stage(
            stage="tests",
            schema=TestsDraft,
            prompt=prompts.render(
                "tests", brief=brief, stories=_compact_stories(ra), apis=_compact_apis(rb), **SIZES
            ),
            extra_checks=lambda m: cross_reference_errors(a=ra, b=rb, c=m),
            **common,
        )
        rc: TestsDraft = c.model  # type: ignore[assignment]
    except AllProvidersFailed as exc:
        log.warning("LLM chain exhausted at stage %s: %s", exc.stage, exc.attempts)
        cached = stale_cache()
        if cached is not None:
            LLM_FALLBACKS.labels("cache").inc()
            return GenerationResult(cached, "cache", attempts=exc.attempts)
        LLM_FALLBACKS.labels("demo").inc()
        draft = DemoProvider().draft_for(brief, signals)
        return GenerationResult(draft, "demo", attempts=exc.attempts)

    stage_providers = {"requirements": a.provider, "design": b.provider, "tests": c.provider}
    badge = "+".join(dict.fromkeys(stage_providers.values()))
    return GenerationResult(
        BlueprintDraft(requirements=ra, design=rb, tests=rc), badge, stage_providers
    )


def default_providers() -> list[LLMProvider]:
    from app.llm.providers.gemini import GeminiProvider
    from app.llm.providers.groq import GroqProvider

    registry: dict[str, Callable[[], LLMProvider]] = {
        "gemini": GeminiProvider,
        "groq": GroqProvider,
        "demo": DemoProvider,
    }
    return [registry[name]() for name in get_settings().llm_providers if name in registry]

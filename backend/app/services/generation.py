"""The generation pipeline a Celery worker runs for one job.

    parsing -> generating_requirements -> generating_design -> generating_tests
            -> saving -> done
(Phase 4 inserts rule_check -> ml_check -> scoring before done.)

Cache: results are keyed by sha256(normalised brief + settings + prompt version).
A hit skips the LLM entirely (badge "cache"). Only real LLM output is cached,
never DemoProvider output.
"""

import hashlib
import json
import logging
import re
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.breaker import Breaker, RedisBreaker
from app.llm.chain import GenerationResult, default_providers, generate_draft
from app.llm.prompts import PROMPT_VERSION
from app.llm.providers.base import LLMProvider
from app.llm.schemas import BlueprintDraft, to_graph
from app.models import Blueprint, GenerationCache
from app.models.enums import BlueprintStatus
from app.nlp.brief import analyze
from app.services import graph

log = logging.getLogger("specforge.generation")
Report = Callable[[str, int, dict[str, Any]], None]


def normalise_brief(brief: str) -> str:
    return re.sub(r"\s+", " ", brief).strip().lower()


def brief_hash(brief: str) -> str:
    return hashlib.sha256(normalise_brief(brief).encode()).hexdigest()


def cache_key(brief: str, settings: dict[str, Any]) -> str:
    material = json.dumps(
        {"brief": normalise_brief(brief), "settings": settings, "prompt": PROMPT_VERSION},
        sort_keys=True,
    )
    return hashlib.sha256(material.encode()).hexdigest()


def _stale_cache_lookup(db: Session, bhash: str) -> Callable[[], BlueprintDraft | None]:
    def lookup() -> BlueprintDraft | None:
        row = db.scalar(
            select(GenerationCache)
            .where(GenerationCache.brief_hash == bhash)
            .order_by(GenerationCache.created_at.desc())
        )
        if row is None:
            return None
        try:
            return BlueprintDraft.model_validate(row.payload)
        except ValueError:
            return None  # schema changed since it was cached

    return lookup


def run_generation(
    db: Session,
    blueprint: Blueprint,
    report: Report,
    *,
    force: bool = False,
    providers: list[LLMProvider] | None = None,
    breaker: Breaker | None = None,
) -> dict[str, Any]:
    """Generate and store the blueprint graph. Returns a small result summary."""
    blueprint.status = BlueprintStatus.generating
    db.commit()

    report("parsing", 5, {})
    signals = analyze(blueprint.brief)

    key = cache_key(blueprint.brief, blueprint.settings)
    cached = None if force else db.get(GenerationCache, key)
    if cached is not None:
        result = GenerationResult(BlueprintDraft.model_validate(cached.payload), "cache")
    else:
        result = generate_draft(
            blueprint.brief,
            signals,
            providers=providers if providers is not None else default_providers(),
            breaker=breaker or RedisBreaker(),
            progress=lambda step, pct: report(step, pct, {}),
            stale_cache=_stale_cache_lookup(db, brief_hash(blueprint.brief)),
        )

    report("saving", 85, {"provider": result.provider})
    nodes, edges = to_graph(result.draft)
    graph.replace_graph(db, blueprint, nodes, edges)  # one transaction

    if result.provider not in ("cache", "demo"):
        row = db.get(GenerationCache, key)
        payload = result.draft.model_dump()
        if row is None:
            db.add(
                GenerationCache(
                    cache_key=key,
                    brief_hash=brief_hash(blueprint.brief),
                    prompt_version=PROMPT_VERSION,
                    provider=result.provider,
                    payload=payload,
                )
            )
        else:
            row.payload, row.provider = payload, result.provider

    blueprint.provider = result.provider
    blueprint.cache_key = key
    blueprint.status = BlueprintStatus.ready
    blueprint.version += 1
    db.commit()
    summary = {
        "provider": result.provider,
        "stage_providers": result.stage_providers,
        "nodes": len(nodes),
        "edges": len(edges),
        "signals": signals.as_dict(),
        "fallback_attempts": result.attempts,
    }
    log.info("blueprint %s generated via %s (%d nodes)", blueprint.id, result.provider, len(nodes))
    return summary

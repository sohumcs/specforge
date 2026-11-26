"""LLM layer: schemas, prompts, adapters, repair loop, fallback chain, demo provider."""

import json

import httpx
import pytest

from app.llm import prompts
from app.llm.breaker import MemoryBreaker, RedisBreaker
from app.llm.chain import AllProvidersFailed, generate_draft, run_stage
from app.llm.jsonschema import strict_schema
from app.llm.providers import demo as demo_mod
from app.llm.providers.base import (
    LLMRequest,
    ProviderBadOutput,
    ProviderConfigError,
    ProviderUnavailable,
)
from app.llm.providers.demo import DemoProvider
from app.llm.providers.gemini import GeminiProvider
from app.llm.providers.groq import GroqProvider
from app.llm.schemas import (
    BlueprintDraft,
    DesignDraft,
    RequirementsDraft,
    cross_reference_errors,
    to_graph,
)
from app.models.enums import EDGE_RULES
from app.nlp.brief import analyze
from tests.llm_fakes import FOOD_BRIEF, ScriptedProvider, stage_payloads, valid_draft

# ------------------------------------------------------------------ schemas & prompts


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


@pytest.mark.parametrize("model", [RequirementsDraft, DesignDraft, BlueprintDraft])
def test_strict_schema_is_self_contained_and_closed(model):
    schema = strict_schema(model)
    text = json.dumps(schema)
    assert "$ref" not in text and "$defs" not in text
    for node in _walk(schema):
        # "title" may legitimately be a *property name*; it must not be schema metadata.
        assert not isinstance(node.get("title"), str)
        if node.get("type") == "object" and "properties" in node:
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])


def test_prompt_render_and_missing_values():
    text = prompts.render("repair", errors="- x")
    assert "- x" in text and "{{" not in text
    with pytest.raises(KeyError):
        prompts.render("repair")


@pytest.mark.parametrize("name", ["system", "requirements", "design", "tests", "repair"])
def test_every_template_exists_for_current_version(name):
    assert prompts.load(name).strip()


def test_cross_reference_errors_finds_problems():
    d = valid_draft()
    assert cross_reference_errors(d.requirements, d.design, d.tests) == []
    bad = d.model_copy(deep=True)
    bad.requirements.stories[0].requirement_refs = ["R99"]
    bad.design.apis[0].module_ref = "M42"
    bad.tests.tests[0].story_refs, bad.tests.tests[0].api_refs = [], []
    bad.design.modules[1].depends_on = [bad.design.modules[1].ref]
    bad.design.entities[1].ref = bad.design.entities[0].ref
    errs = cross_reference_errors(bad.requirements, bad.design, bad.tests)
    joined = "\n".join(errs)
    assert "unknown requirement R99" in joined
    assert "unknown module M42" in joined
    assert "must verify at least one" in joined
    assert "depends on unknown module" in joined
    assert "used more than once" in joined


def test_to_graph_edges_respect_type_rules():
    nodes, edges = to_graph(valid_draft())
    types = {n.ref: n.type for n in nodes}
    for e in edges:
        assert (types[e.src], types[e.dst]) in EDGE_RULES[e.type], e


def test_api_path_must_start_with_slash():
    data = stage_payloads()["design"]
    data["apis"][0]["path"] = "orders"
    with pytest.raises(ValueError):
        DesignDraft.model_validate(data)


# ------------------------------------------------------------------ run_stage


def _run(providers, breaker=None, sleep=lambda s: None):
    return run_stage(
        stage="requirements",
        schema=RequirementsDraft,
        prompt="p",
        context={"brief": "b"},
        providers=providers,
        breaker=breaker or MemoryBreaker(),
        extra_checks=lambda m: cross_reference_errors(a=m),
        sleep=sleep,
    )


def test_first_valid_answer_wins():
    p = ScriptedProvider("gemini")
    r = _run([p, ScriptedProvider("groq")])
    assert r.provider == "gemini" and r.repairs == 0 and len(p.requests) == 1


def test_invalid_output_triggers_repair_with_errors_fed_back():
    broken = stage_payloads()["requirements"]
    broken["stories"][0]["requirement_refs"] = ["R404"]
    p = ScriptedProvider("gemini", [broken, "valid"])
    r = _run([p])
    assert r.repairs == 1
    repair_prompt = p.requests[1].history[-1][1]
    assert "R404" in repair_prompt and "Return the COMPLETE corrected JSON" in repair_prompt
    assert json.loads(p.requests[1].history[-1][0])["stories"][0]["requirement_refs"] == ["R404"]


def test_schema_violation_and_bad_json_are_repaired():
    p = ScriptedProvider(
        "gemini",
        [{"requirements": "nope"}, ProviderBadOutput("invalid JSON", raw="{oops"), "valid"],
    )
    r = _run([p])
    assert r.repairs == 2
    assert "requirements" in p.requests[1].history[0][1]


def test_repairs_exhausted_moves_to_next_provider():
    bad = {"requirements": []}
    p1 = ScriptedProvider("gemini", [bad, bad, bad])
    p2 = ScriptedProvider("groq")
    r = _run([p1, p2])
    assert r.provider == "groq" and len(p1.requests) == 3


def test_unavailable_trips_breaker_and_falls_through():
    breaker = MemoryBreaker()
    p1 = ScriptedProvider("gemini", [ProviderUnavailable("429", retry_after=3600)])
    r = _run([p1, ScriptedProvider("groq")], breaker=breaker)
    assert r.provider == "groq" and breaker.is_open("gemini")
    # next stage skips gemini entirely while the circuit is open
    p1b = ScriptedProvider("gemini")
    _run([p1b, ScriptedProvider("groq")], breaker=breaker)
    assert p1b.requests == []


def test_short_retry_after_waits_then_retries_same_provider():
    slept = []
    p = ScriptedProvider("groq", [ProviderUnavailable("429", retry_after=2.5), "valid"])
    r = _run([p], sleep=slept.append)
    assert r.provider == "groq" and slept == [2.5]


def test_config_error_and_unconfigured_are_skipped():
    p0 = ScriptedProvider("nokey", configured=False)
    p1 = ScriptedProvider("gemini", [ProviderConfigError("401")])
    r = _run([p0, p1, ScriptedProvider("groq")])
    assert r.provider == "groq" and p0.requests == []


def test_all_fail_raises_with_attempt_log():
    with pytest.raises(AllProvidersFailed) as exc:
        _run(
            [
                ScriptedProvider("gemini", [ProviderUnavailable("down")]),
                ScriptedProvider("groq", [ProviderConfigError("bad key")]),
            ]
        )
    outcomes = [a["outcome"] for a in exc.value.attempts]
    assert outcomes == ["unavailable", "config_error"]


# ------------------------------------------------------------------ generate_draft


def test_generate_draft_mixed_providers_badge():
    sig = analyze(FOOD_BRIEF)
    g = ScriptedProvider("gemini", ["valid", ProviderUnavailable("down", retry_after=999)])
    res = generate_draft(
        FOOD_BRIEF,
        sig,
        providers=[g, ScriptedProvider("groq")],
        breaker=MemoryBreaker(),
        sleep=lambda s: None,
    )
    assert res.provider == "gemini+groq"
    assert res.stage_providers == {"requirements": "gemini", "design": "groq", "tests": "groq"}


def test_generate_draft_falls_back_to_stale_cache_then_demo():
    sig = analyze(FOOD_BRIEF)
    down = [ScriptedProvider("gemini", [ProviderUnavailable("down")])]
    cached = valid_draft()
    res = generate_draft(
        FOOD_BRIEF, sig, providers=down, breaker=MemoryBreaker(), stale_cache=lambda: cached
    )
    assert res.provider == "cache" and res.draft == cached
    res2 = generate_draft(FOOD_BRIEF, sig, providers=[], breaker=MemoryBreaker())
    assert res2.provider == "demo"
    assert (
        cross_reference_errors(res2.draft.requirements, res2.draft.design, res2.draft.tests) == []
    )


def test_progress_callback_reports_each_stage():
    steps = []
    generate_draft(
        FOOD_BRIEF,
        analyze(FOOD_BRIEF),
        providers=[ScriptedProvider("g")],
        breaker=MemoryBreaker(),
        progress=lambda s, p: steps.append((s, p)),
    )
    assert [s for s, _ in steps] == [
        "generating_requirements",
        "generating_design",
        "generating_tests",
    ]


# ------------------------------------------------------------------ HTTP adapters


def _req(history=None):
    return LLMRequest(
        stage="requirements",
        system="sys",
        prompt="hello",
        json_schema={"type": "object"},
        schema_name="X",
        history=history or [],
    )


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_gemini_request_shape_and_parse():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers["x-goog-api-key"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}],
                "usageMetadata": {"totalTokenCount": 5},
            },
        )

    p = GeminiProvider(api_key="k", model="gemini-test", client=_client(handler))
    r = p.complete_json(_req(history=[("{}", "fix it")]))
    assert r.data == {"ok": True} and r.usage["totalTokenCount"] == 5
    assert seen["url"].endswith("/models/gemini-test:generateContent") and seen["key"] == "k"
    cfg = seen["body"]["generationConfig"]
    assert cfg["responseMimeType"] == "application/json" and cfg["responseJsonSchema"]
    assert [c["role"] for c in seen["body"]["contents"]] == ["user", "model", "user"]


@pytest.mark.parametrize(
    ("status", "exc_type"),
    [
        (429, ProviderUnavailable),
        (503, ProviderUnavailable),
        (401, ProviderConfigError),
        (400, ProviderConfigError),
    ],
)
def test_gemini_error_classification(status, exc_type):
    p = GeminiProvider(
        api_key="k",
        client=_client(lambda r: httpx.Response(status, headers={"retry-after": "7"}, json={})),
    )
    with pytest.raises(exc_type) as exc:
        p.complete_json(_req())
    if exc_type is ProviderUnavailable:
        assert exc.value.retry_after == 7


@pytest.mark.parametrize(
    "payload",
    [
        {"candidates": []},
        {"candidates": [{"content": {"parts": [{"text": "not json"}]}}]},
        {"candidates": [{"content": {"parts": [{"text": "[1, 2]"}]}}]},
    ],
)
def test_gemini_bad_output(payload):
    p = GeminiProvider(api_key="k", client=_client(lambda r: httpx.Response(200, json=payload)))
    with pytest.raises(ProviderBadOutput):
        p.complete_json(_req())


def test_gemini_retry_delay_read_from_error_body():
    body = {
        "error": {
            "code": 429,
            "details": [
                {"@type": "type.googleapis.com/google.rpc.QuotaFailure"},
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "13s"},
            ],
        }
    }
    p = GeminiProvider(api_key="k", client=_client(lambda r: httpx.Response(429, json=body)))
    with pytest.raises(ProviderUnavailable) as exc:
        p.complete_json(_req())
    assert exc.value.retry_after == 13.0


def test_gemini_transport_error_is_unavailable():
    def boom(request):
        raise httpx.ConnectTimeout("slow")

    with pytest.raises(ProviderUnavailable):
        GeminiProvider(api_key="k", client=_client(boom)).complete_json(_req())


def test_groq_request_shape_and_errors():
    seen = {}

    def ok(request):
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"a": 1}'}}], "usage": {"total_tokens": 3}},
        )

    p = GroqProvider(api_key="g", model="openai/gpt-oss-120b", client=_client(ok))
    assert p.complete_json(_req()).data == {"a": 1}
    assert seen["auth"] == "Bearer g"
    rf = seen["body"]["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True
    assert seen["body"]["reasoning_effort"] == "low"

    bad = GroqProvider(
        api_key="g",
        client=_client(
            lambda r: httpx.Response(400, json={"error": {"code": "json_validate_failed"}})
        ),
    )
    with pytest.raises(ProviderBadOutput):
        bad.complete_json(_req())
    down = GroqProvider(api_key="g", client=_client(lambda r: httpx.Response(503)))
    with pytest.raises(ProviderUnavailable):
        down.complete_json(_req())


def test_unconfigured_providers():
    assert not GeminiProvider(api_key="").configured()
    assert not GroqProvider(api_key="").configured()


# ------------------------------------------------------------------ demo provider & breaker


def test_demo_is_deterministic_and_valid():
    a = DemoProvider().draft_for("Students enroll in courses and teachers grade assignments.")
    b = DemoProvider().draft_for("Students enroll in courses and teachers grade assignments.")
    assert a == b
    assert cross_reference_errors(a.requirements, a.design, a.tests) == []


def test_demo_handles_tiny_brief():
    d = DemoProvider().draft_for("A tiny tool for notes.")
    assert len(d.requirements.requirements) >= 3


def test_demo_complete_json_returns_stage_slice():
    r = DemoProvider().complete_json(
        LLMRequest(
            stage="design",
            system="",
            prompt="",
            json_schema={},
            schema_name="D",
            context={"brief": FOOD_BRIEF},
        )
    )
    DesignDraft.model_validate(r.data)
    assert r.provider == "demo"


def test_demo_sample_matching(tmp_path, monkeypatch):
    sample = {
        "slug": "x",
        "title": "X",
        "brief": "b",
        "keywords": ["rocket", "launch", "orbit"],
        "draft": valid_draft().model_dump(),
    }
    (tmp_path / "x.json").write_text(json.dumps(sample))
    monkeypatch.setattr(demo_mod, "DATA_DIR", tmp_path)
    demo_mod.load_samples.cache_clear()
    try:
        assert demo_mod.match_sample("We launch a rocket into orbit") is not None
        assert demo_mod.match_sample("We launch a rocket") is None  # only 2 keyword hits
        assert DemoProvider().draft_for("rocket launch orbit tracker") == valid_draft()
    finally:
        demo_mod.load_samples.cache_clear()


def test_redis_breaker_roundtrip_and_fails_open():
    import redis as redis_lib

    from app.core.config import get_settings

    client = redis_lib.Redis.from_url(get_settings().redis_url)
    b = RedisBreaker(client)
    b.trip("testprov", 5)
    assert b.is_open("testprov") and 0 < b.remaining("testprov") <= 5
    client.delete("specforge:llm:breaker:testprov")
    assert not b.is_open("testprov")
    dead = RedisBreaker(redis_lib.Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.2))
    assert dead.is_open("x") is False
    dead.trip("x", 5)  # must not raise
    assert dead.remaining("x") == 0

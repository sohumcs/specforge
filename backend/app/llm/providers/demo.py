"""DemoProvider: deterministic, offline, never fails.

It is the last link of the fallback chain, so the public demo keeps working
when every free LLM quota is exhausted or no keys are configured.

1. If the brief clearly matches one of the curated sample blueprints
   (`app/llm/demo_data/*.json`, produced by a real LLM run and reviewed), that
   sample is returned.
2. Otherwise a blueprint is *assembled* from the brief's spaCy signals
   (actors, entities, verb-object actions) using templates. That's less rich
   than an LLM, but it is specific to the brief and always passes validation.

Same brief in, same blueprint out.
"""

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.llm.providers.base import LLMRequest, LLMResponse
from app.llm.schemas import BlueprintDraft
from app.nlp.brief import BriefSignals, analyze

DATA_DIR = Path(__file__).resolve().parent.parent / "demo_data"
STAGE_KEYS = {"requirements": "requirements", "design": "design", "tests": "tests"}
MIN_KEYWORD_HITS = 3


@lru_cache(maxsize=1)
def load_samples() -> list[dict[str, Any]]:
    samples = []
    for path in sorted(DATA_DIR.glob("*.json")):
        sample = json.loads(path.read_text(encoding="utf-8"))
        BlueprintDraft.model_validate(sample["draft"])  # fail fast on a broken sample file
        samples.append(sample)
    return samples


def match_sample(brief: str) -> dict[str, Any] | None:
    words = set(re.findall(r"[a-z]+", brief.lower()))
    best, best_hits = None, 0
    for sample in load_samples():
        hits = sum(1 for k in sample["keywords"] if k in words)
        if hits > best_hits:
            best, best_hits = sample, hits
    return best if best_hits >= MIN_KEYWORD_HITS else None


class DemoProvider:
    name = "demo"
    model = "templates-v1"

    def configured(self) -> bool:
        return True

    def draft_for(self, brief: str, signals: BriefSignals | None = None) -> BlueprintDraft:
        sample = match_sample(brief)
        if sample is not None:
            return BlueprintDraft.model_validate(sample["draft"])
        return assemble(signals or analyze(brief))

    def complete_json(self, request: LLMRequest) -> LLMResponse:
        draft = self.draft_for(request.context["brief"])
        data = getattr(draft, STAGE_KEYS[request.stage]).model_dump()
        return LLMResponse(data=data, provider=self.name, model=self.model)


# ---------------------------------------------------------------------------- templates


def _plural(word: str) -> str:
    if word.endswith("y") and word[-2:-1] not in "aeiou":
        return word[:-1] + "ies"
    if word.endswith(("s", "x", "ch", "sh")):
        return word + "es"
    return word + "s"


def _kebab(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


BENEFIT = {
    "order": "I get what I need without phoning anyone",
    "book": "I secure a slot that suits me",
    "track": "I always know the current status",
    "pay": "I can complete the purchase securely",
    "manage": "the information stays accurate",
    "view": "I can make informed decisions",
    "cancel": "plans can change without penalty",
    "approve": "only valid requests go through",
}


def assemble(sig: BriefSignals) -> BlueprintDraft:
    actors = [a for a in sig.actors if a != "user"][:4] or ["user"]
    entity_names = [e for e in sig.entities if e.lower() not in sig.actors][:5]
    if not entity_names:
        entity_names = ["Item"]
    actions = [(v, o, a) for v, o, a in sig.actions if v not in ("be", "have", "do")][:7]
    for e in entity_names:
        if len(actions) >= 3:
            break
        actions.append(("manage", e.lower(), ""))

    reqs: list[dict[str, Any]] = []
    stories: list[dict[str, Any]] = []

    def add(
        kind: str, cat: str, title: str, desc: str, prio: str, story: str, criteria: list[str]
    ) -> None:
        r, s = f"R{len(reqs) + 1}", f"S{len(stories) + 1}"
        reqs.append(
            {
                "ref": r,
                "kind": kind,
                "nfr_category": cat,
                "title": title,
                "description": desc,
                "priority": prio,
            }
        )
        stories.append(
            {"ref": s, "requirement_refs": [r], "title": story, "acceptance_criteria": criteria}
        )

    add(
        "functional",
        "none",
        "Users can sign up, sign in and manage their profile",
        "Email/password accounts with role-based access.",
        "must",
        "As a user, I want to sign in securely so that my data is only visible to me",
        [
            "Given valid credentials, when I sign in, then I reach my dashboard",
            "Given a wrong password, when I sign in, then I see a generic error",
        ],
    )
    for i, (verb, obj, subject) in enumerate(actions):
        actor = subject if subject in sig.actors else actors[i % len(actors)]
        add(
            "functional",
            "none",
            f"{actor.capitalize()} can {verb} {obj}",
            f"Supports the '{verb} {obj}' workflow described in the brief.",
            "must" if i < 3 else "should",
            f"As {_article(actor)} {actor}, I want to {verb} {obj} so that "
            f"{BENEFIT.get(verb, 'my work gets done faster')}",
            [
                f"Given I am signed in as {_article(actor)} {actor}, when I {verb} {obj}, "
                f"then the change is saved and confirmed",
                f"Given invalid input, when I try to {verb} {obj}, then I see what to fix",
            ],
        )
    nfr_start = len(reqs)
    add(
        "non_functional",
        "performance",
        "Core API responds quickly",
        "p95 latency under 300 ms for read endpoints at 50 requests/second.",
        "should",
        "As an operator, I want p95 API latency under 300 ms so that the app feels instant",
        ["Given 50 req/s of mixed reads, when load-tested, then p95 is under 300 ms"],
    )
    add(
        "non_functional",
        "security",
        "Data and access are protected",
        "JWT auth, role-based authorisation, OWASP Top 10 mitigations, TLS everywhere.",
        "must",
        "As an admin, I want every endpoint to enforce roles so that users only see their data",
        ["Given a viewer token, when calling a write endpoint, then the API returns 403"],
    )
    add(
        "non_functional",
        "availability",
        "Service stays available",
        "99.5% monthly uptime with health checks and automatic restarts.",
        "should",
        "As an operator, I want health checks and auto-restarts so that outages are short",
        ["Given a crashed instance, when the probe fails, then it is restarted within 60 s"],
    )

    risks = [
        {
            "ref": "K1",
            "title": "Third-party dependency outage",
            "description": "Payment, SMS or map providers may be unavailable.",
            "likelihood": "medium",
            "impact": "high",
            "mitigation": "Timeouts, retries with backoff and a degraded mode per provider.",
            "requirement_refs": [reqs[1]["ref"]],
        },
        {
            "ref": "K2",
            "title": "Personal data breach",
            "description": "User data could leak through misconfigured access control.",
            "likelihood": "low",
            "impact": "high",
            "mitigation": "RBAC tests in CI, least-privilege DB roles, encrypted backups.",
            "requirement_refs": [reqs[nfr_start + 1]["ref"]],
        },
        {
            "ref": "K3",
            "title": "Scope creep delays launch",
            "description": "New feature requests during build push the release date.",
            "likelihood": "medium",
            "impact": "medium",
            "mitigation": "Freeze MVP scope; route new ideas through a change log.",
            "requirement_refs": [reqs[0]["ref"]],
        },
    ]

    # ---- design: one module per domain entity (+ identity, + platform)
    modules: list[dict[str, Any]] = [
        {
            "ref": "M1",
            "name": "Identity & Access",
            "responsibility": "Accounts, sessions and role-based authorisation.",
            "story_refs": [stories[0]["ref"], stories[nfr_start + 1]["ref"]],
            "depends_on": [],
        }
    ]
    entity_module: dict[str, str] = {"User": "M1"}
    for name in entity_names[:4]:
        ref = f"M{len(modules) + 1}"
        modules.append(
            {
                "ref": ref,
                "name": f"{name} Management",
                "responsibility": f"Business rules and storage for {_plural(name.lower())}.",
                "story_refs": [],
                "depends_on": ["M1"],
            }
        )
        entity_module[name] = ref
    platform = f"M{len(modules) + 1}"
    modules.append(
        {
            "ref": platform,
            "name": "Platform & Observability",
            "responsibility": "Health checks, metrics, caching and deployment.",
            "story_refs": [stories[nfr_start]["ref"], stories[nfr_start + 2]["ref"]],
            "depends_on": [],
        }
    )
    domain = [m for m in modules if m["ref"] not in ("M1", platform)]
    for i, (_, obj, _actor) in enumerate(actions):
        story_ref = stories[i + 1]["ref"]
        target = entity_module.get(obj.capitalize()) or domain[i % len(domain)]["ref"]
        next(m for m in modules if m["ref"] == target)["story_refs"].append(story_ref)

    all_entities = ["User", *[n for n in entity_names if n != "User"]][:6]
    entities: list[dict[str, Any]] = []
    for i, name in enumerate(all_entities):
        fields = [{"name": "id", "type": "uuid", "primary_key": True, "nullable": False}]
        if name == "User":
            fields += [
                {"name": "email", "type": "string", "primary_key": False, "nullable": False},
                {"name": "role", "type": "string", "primary_key": False, "nullable": False},
            ]
            relations: list[dict[str, str]] = []
        else:
            fields += [
                {"name": "name", "type": "string", "primary_key": False, "nullable": False},
                {"name": "status", "type": "string", "primary_key": False, "nullable": False},
                {"name": "user_id", "type": "uuid", "primary_key": False, "nullable": False},
            ]
            relations = [{"target_ref": "E1", "kind": "many_to_one"}]
        fields.append(
            {"name": "created_at", "type": "timestamp", "primary_key": False, "nullable": False}
        )
        entities.append(
            {
                "ref": f"E{i + 1}",
                "name": name,
                "description": f"A {name.lower()} in the system.",
                "fields": fields,
                "relations": relations,
            }
        )

    apis: list[dict[str, Any]] = []

    def api(method: str, path: str, summary: str, module: str, entity: str) -> None:
        if len(apis) < 22:
            apis.append(
                {
                    "ref": f"A{len(apis) + 1}",
                    "method": method,
                    "path": path,
                    "summary": summary,
                    "module_ref": module,
                    "entity_refs": [entity],
                }
            )

    api("POST", "/sessions", "Sign in and receive tokens", "M1", "E1")
    api("GET", "/users/me", "Current user's profile", "M1", "E1")
    for ent in entities[1:]:
        plural = "/" + _plural(_kebab(ent["name"]))
        mod = entity_module.get(ent["name"], domain[0]["ref"])
        low = ent["name"].lower()
        api("GET", plural, f"List {_plural(low)}", mod, ent["ref"])
        api("POST", plural, f"Create {_article(low)} {low}", mod, ent["ref"])
        api("GET", plural + "/{id}", f"Get one {low}", mod, ent["ref"])
        api("PATCH", plural + "/{id}", f"Update {_article(low)} {low}", mod, ent["ref"])
        api("DELETE", plural + "/{id}", f"Delete {_article(low)} {low}", mod, ent["ref"])

    tests: list[dict[str, Any]] = []
    for s in stories[:nfr_start]:
        tests.append(
            {
                "ref": f"T{len(tests) + 1}",
                "title": f"E2E: {s['title'][:80]}",
                "kind": "e2e",
                "story_refs": [s["ref"]],
                "api_refs": [],
                "steps": [
                    "Sign in as the story's actor",
                    "Perform the action",
                    "Verify the confirmation and stored state",
                ],
            }
        )
    tests.append(
        {
            "ref": f"T{len(tests) + 1}",
            "title": "Rejects invalid create payload",
            "kind": "integration",
            "story_refs": [],
            "api_refs": [apis[3]["ref"] if len(apis) > 3 else apis[0]["ref"]],
            "steps": ["POST with a missing required field", "Expect HTTP 422"],
        }
    )
    tests.append(
        {
            "ref": f"T{len(tests) + 1}",
            "title": "p95 latency under load",
            "kind": "performance",
            "story_refs": [stories[nfr_start]["ref"]],
            "api_refs": [apis[2]["ref"] if len(apis) > 2 else apis[0]["ref"]],
            "steps": ["Run 50 req/s for 5 minutes", "Assert p95 < 300 ms"],
        }
    )
    tests.append(
        {
            "ref": f"T{len(tests) + 1}",
            "title": "Viewer cannot write",
            "kind": "security",
            "story_refs": [stories[nfr_start + 1]["ref"]],
            "api_refs": [apis[0]["ref"]],
            "steps": ["Sign in as a viewer", "Call a write endpoint", "Expect HTTP 403"],
        }
    )
    tests.append(
        {
            "ref": f"T{len(tests) + 1}",
            "title": "Crashed instance is restarted",
            "kind": "integration",
            "story_refs": [stories[nfr_start + 2]["ref"]],
            "api_refs": [],
            "steps": ["Kill the API process", "Wait 60 s", "Expect /health to return 200"],
        }
    )

    return BlueprintDraft.model_validate(
        {
            "requirements": {"requirements": reqs, "stories": stories, "risks": risks},
            "design": {"modules": modules, "entities": entities, "apis": apis},
            "tests": {"tests": tests[:20]},
        }
    )

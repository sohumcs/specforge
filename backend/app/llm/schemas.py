"""Structured-output contracts for blueprint generation.

Generation runs in three stages so each LLM call stays small (Groq's free tier
caps a minute at 8K tokens, reasoning tokens included):

  A. RequirementsDraft  requirements, user stories, risks
  B. DesignDraft        modules, entities, REST endpoints   (sees A)
  C. TestsDraft         test scenarios                      (sees A + B)

The models deliberately avoid Optional fields and defaults: strict JSON-schema
modes (Groq) require every property to be present. "No value" is "" or [].

Pydantic validates shape. `cross_reference_errors` validates meaning (every
`*_refs` points at something that exists). Both kinds of error are fed back to
the model in a repair prompt.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.enums import EdgeType, NodeType
from app.services.graph import EdgeSpec, NodeSpec

Priority = Literal["must", "should", "could"]
Level = Literal["low", "medium", "high"]
NfrCategory = Literal[
    "none", "performance", "security", "availability", "scalability", "usability", "compliance"
]
HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
TestKind = Literal["unit", "integration", "e2e", "performance", "security"]
RelationKind = Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"]

REF = r"^[A-Z]{1,3}\d{1,3}$"


class _Strict(BaseModel):
    model_config = {"extra": "forbid"}


# ------------------------------------------------------------------ stage A


class RequirementDraft(_Strict):
    ref: str = Field(pattern=REF, description="R1, R2, ...")
    kind: Literal["functional", "non_functional"]
    nfr_category: NfrCategory
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(max_length=1000)
    priority: Priority


class StoryDraft(_Strict):
    ref: str = Field(pattern=REF, description="S1, S2, ...")
    requirement_refs: list[str] = Field(min_length=1)
    title: str = Field(
        min_length=10, max_length=300, description="As a <role>, I want ... so that ..."
    )
    acceptance_criteria: list[str] = Field(min_length=1, max_length=6)


class RiskDraft(_Strict):
    ref: str = Field(pattern=REF, description="K1, K2, ...")
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(max_length=1000)
    likelihood: Level
    impact: Level
    mitigation: str = Field(max_length=1000)
    requirement_refs: list[str]


class RequirementsDraft(_Strict):
    requirements: list[RequirementDraft] = Field(min_length=3, max_length=14)
    stories: list[StoryDraft] = Field(min_length=3, max_length=18)
    risks: list[RiskDraft] = Field(min_length=1, max_length=6)


# ------------------------------------------------------------------ stage B


class FieldDraft(_Strict):
    name: str = Field(min_length=1, max_length=60)
    type: str = Field(min_length=1, max_length=40)
    primary_key: bool
    nullable: bool


class RelationDraft(_Strict):
    target_ref: str
    kind: RelationKind


class EntityDraft(_Strict):
    ref: str = Field(pattern=REF, description="E1, E2, ...")
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(max_length=500)
    fields: list[FieldDraft] = Field(min_length=1, max_length=20)
    relations: list[RelationDraft]


class ModuleDraft(_Strict):
    ref: str = Field(pattern=REF, description="M1, M2, ...")
    name: str = Field(min_length=1, max_length=80)
    responsibility: str = Field(max_length=500)
    story_refs: list[str]
    depends_on: list[str]


class ApiDraft(_Strict):
    ref: str = Field(pattern=REF, description="A1, A2, ...")
    method: HttpMethod
    path: str = Field(min_length=1, max_length=200)
    summary: str = Field(max_length=300)
    module_ref: str
    entity_refs: list[str]

    @field_validator("path")
    @classmethod
    def _path_shape(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError("path must start with '/'")
        return v


class DesignDraft(_Strict):
    modules: list[ModuleDraft] = Field(min_length=2, max_length=10)
    entities: list[EntityDraft] = Field(min_length=2, max_length=10)
    apis: list[ApiDraft] = Field(min_length=3, max_length=22)


# ------------------------------------------------------------------ stage C


class TestDraft(_Strict):
    __test__ = False  # not a pytest class

    ref: str = Field(pattern=REF, description="T1, T2, ...")
    title: str = Field(min_length=3, max_length=200)
    kind: TestKind
    story_refs: list[str]
    api_refs: list[str]
    steps: list[str] = Field(max_length=8)


class TestsDraft(_Strict):
    __test__ = False

    tests: list[TestDraft] = Field(min_length=3, max_length=20)


# ------------------------------------------------------------------ whole blueprint


class BlueprintDraft(_Strict):
    requirements: RequirementsDraft
    design: DesignDraft
    tests: TestsDraft


def _dupes(refs: list[str]) -> list[str]:
    seen: set[str] = set()
    dupes: set[str] = set()
    for r in refs:
        (dupes if r in seen else seen).add(r)
    return sorted(dupes)


def cross_reference_errors(
    a: RequirementsDraft | None = None,
    b: DesignDraft | None = None,
    c: TestsDraft | None = None,
) -> list[str]:
    """Human-readable problems the model must fix (empty list = consistent)."""
    errors: list[str] = []
    req = {r.ref for r in a.requirements} if a else set()
    sto = {s.ref for s in a.stories} if a else set()
    mod = {m.ref for m in b.modules} if b else set()
    ent = {e.ref for e in b.entities} if b else set()
    api = {x.ref for x in b.apis} if b else set()

    all_refs: list[str] = []
    if a:
        all_refs += [r.ref for r in a.requirements] + [s.ref for s in a.stories]
        all_refs += [k.ref for k in a.risks]
        for s in a.stories:
            errors += [
                f"story {s.ref} references unknown requirement {r}"
                for r in s.requirement_refs
                if r not in req
            ]
        for k in a.risks:
            errors += [
                f"risk {k.ref} references unknown requirement {r}"
                for r in k.requirement_refs
                if r not in req
            ]
    if b:
        all_refs += [m.ref for m in b.modules] + [e.ref for e in b.entities]
        all_refs += [x.ref for x in b.apis]
        for m in b.modules:
            errors += [
                f"module {m.ref} references unknown story {s}"
                for s in m.story_refs
                if a and s not in sto
            ]
            errors += [
                f"module {m.ref} depends on unknown module {d}"
                for d in m.depends_on
                if d not in mod or d == m.ref
            ]
        for e in b.entities:
            errors += [
                f"entity {e.ref} relates to unknown entity {r.target_ref}"
                for r in e.relations
                if r.target_ref not in ent
            ]
        for x in b.apis:
            if x.module_ref not in mod:
                errors.append(f"api {x.ref} belongs to unknown module {x.module_ref}")
            errors += [
                f"api {x.ref} references unknown entity {e}" for e in x.entity_refs if e not in ent
            ]
    if c:
        all_refs += [t.ref for t in c.tests]
        for t in c.tests:
            errors += [
                f"test {t.ref} references unknown story {s}" for s in t.story_refs if s not in sto
            ]
            errors += [
                f"test {t.ref} references unknown api {x}" for x in t.api_refs if x not in api
            ]
            if not t.story_refs and not t.api_refs:
                errors.append(f"test {t.ref} must verify at least one story or api")
    errors += [f"ref {r} is used more than once" for r in _dupes(all_refs)]
    return errors


_SLUG = re.compile(r"[^a-z0-9]+")


def to_graph(draft: BlueprintDraft) -> tuple[list[NodeSpec], list[EdgeSpec]]:
    """Flatten a validated draft into graph node/edge specs (refs as handles)."""
    a, b, c = draft.requirements, draft.design, draft.tests
    T, E = NodeType, EdgeType
    nodes: list[NodeSpec] = []
    edges: list[EdgeSpec] = []

    for r in a.requirements:
        nodes.append(
            NodeSpec(
                r.ref,
                T.requirement,
                r.title,
                {
                    "kind": r.kind,
                    "nfr_category": r.nfr_category,
                    "description": r.description,
                    "priority": r.priority,
                },
            )
        )
    for s in a.stories:
        nodes.append(
            NodeSpec(s.ref, T.story, s.title, {"acceptance_criteria": s.acceptance_criteria})
        )
        edges += [EdgeSpec(r, s.ref, E.refines) for r in s.requirement_refs]
    for m in b.modules:
        nodes.append(NodeSpec(m.ref, T.module, m.name, {"responsibility": m.responsibility}))
        edges += [EdgeSpec(s, m.ref, E.implemented_by) for s in m.story_refs]
        edges += [EdgeSpec(m.ref, d, E.depends_on) for d in m.depends_on if d != m.ref]
    for e in b.entities:
        nodes.append(
            NodeSpec(
                e.ref,
                T.entity,
                e.name,
                {
                    "description": e.description,
                    "fields": [f.model_dump() for f in e.fields],
                    "relations": [r.model_dump() for r in e.relations],
                },
            )
        )
    for e in b.entities:
        edges += [
            EdgeSpec(e.ref, r.target_ref, E.relates_to, {"kind": r.kind})
            for r in e.relations
            if r.target_ref != e.ref
        ]
    for x in b.apis:
        nodes.append(
            NodeSpec(
                x.ref,
                T.api,
                f"{x.method} {x.path}",
                {"method": x.method, "path": x.path, "summary": x.summary},
            )
        )
        edges.append(EdgeSpec(x.module_ref, x.ref, E.exposes))
        edges += [EdgeSpec(x.ref, e, E.persists) for e in x.entity_refs]
    for t in c.tests:
        nodes.append(NodeSpec(t.ref, T.test, t.title, {"kind": t.kind, "steps": t.steps}))
        edges += [EdgeSpec(s, t.ref, E.verified_by) for s in t.story_refs]
        edges += [EdgeSpec(x, t.ref, E.verified_by) for x in t.api_refs]
    for k in a.risks:
        nodes.append(
            NodeSpec(
                k.ref,
                T.risk,
                k.title,
                {
                    "description": k.description,
                    "likelihood": k.likelihood,
                    "impact": k.impact,
                    "mitigation": k.mitigation,
                },
            )
        )
        edges += [EdgeSpec(k.ref, r, E.threatens) for r in k.requirement_refs]
    return nodes, edges

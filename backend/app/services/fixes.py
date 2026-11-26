"""One-click "fix with AI" for quality issues, and subgraph regeneration.

Each rule code maps to a fixer. Fixers that don't need language generation are
deterministic and use embeddings for judgement ("link this orphan story to the
most similar requirement"). Generative fixers make one small LLM call through
the same fallback chain as generation and fall back to a template, so a fix
never fails because a quota ran out.

Every fix runs in one transaction and is followed by a full re-verification,
so the job result reports the score before and after.
"""

import json
import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

import numpy as np
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.llm import prompts
from app.llm.breaker import Breaker, RedisBreaker
from app.llm.chain import AllProvidersFailed, default_providers, run_stage
from app.llm.fix_schemas import (
    CriteriaFix,
    MitigationFix,
    NewStory,
    NewTest,
    NfrFix,
    RewriteFix,
    StoriesFix,
    SubgraphUpdate,
    TestsFix,
)
from app.llm.providers.base import LLMProvider
from app.models import Blueprint, Edge, Issue, Node, QualityReport
from app.models.enums import EDGE_RULES, EdgeType, NodeType
from app.services import graph
from app.services.verification import ensure_embeddings, run_verification
from app.verify.rules import CRUD, path_problems

log = logging.getLogger("specforge.fixes")
M = TypeVar("M", bound=BaseModel)
Report = Callable[[str, int, dict[str, Any]], None]
E, T = EdgeType, NodeType


class FixNotPossible(AppError):
    code = "FIX_NOT_POSSIBLE"


@dataclass
class FixContext:
    db: Session
    blueprint: Blueprint
    issue: Issue
    providers: list[LLMProvider]
    breaker: Breaker
    nodes: dict[uuid.UUID, Node] = field(default_factory=dict)
    provider_used: str = "deterministic"
    changed: list[str] = field(default_factory=list)

    # ---------------------------------------------------------------- helpers

    def node(self, i: int = 0) -> Node:
        try:
            return self.nodes[uuid.UUID(str(self.issue.node_ids[i]))]
        except (IndexError, KeyError) as exc:
            raise FixNotPossible("The nodes in this issue no longer exist") from exc

    def of_type(self, t: NodeType) -> list[Node]:
        return sorted((n for n in self.nodes.values() if n.type == t), key=lambda n: n.position)

    def most_similar(self, target: Node, candidates: list[Node]) -> Node:
        if not candidates:
            raise FixNotPossible("There are no suitable nodes to link to")
        ensure_embeddings(self.db, [target, *candidates])
        v = np.asarray(target.embedding, dtype=np.float32)
        sims = [float(np.asarray(c.embedding, dtype=np.float32) @ v) for c in candidates]
        return candidates[int(np.argmax(sims))]

    def add_node(self, t: NodeType, title: str, body: dict[str, Any]) -> Node:
        node = graph.create_node(
            self.db, self.blueprint, node_type=t, title=title, body=body, commit=False
        )
        self.nodes[node.id] = node
        self.changed.append(node.key)
        return node

    def link(self, src: Node, dst: Node, t: EdgeType) -> None:
        exists = self.db.scalar(
            select(Edge.id).where(Edge.src_id == src.id, Edge.dst_id == dst.id, Edge.type == t)
        )
        if not exists:
            graph.create_edge(
                self.db,
                self.blueprint,
                src_id=src.id,
                dst_id=dst.id,
                edge_type=t,
                body={},
                commit=False,
            )

    def llm(self, schema: type[M], task: str, context: Any, fallback: Callable[[], M]) -> M:
        prompt = prompts.render(
            "fix",
            brief=self.blueprint.brief,
            task=task,
            context=json.dumps(context, default=str)[:6000],
        )
        try:
            result = run_stage(
                stage="fix",
                schema=schema,
                prompt=prompt,
                context={"brief": self.blueprint.brief},
                providers=[p for p in self.providers if p.name != "demo"],
                breaker=self.breaker,
                extra_checks=lambda m: [],
            )
            self.provider_used = result.provider
            return result.model  # type: ignore[return-value]
        except AllProvidersFailed:
            self.provider_used = "demo"
            return fallback()


def _ctx_nodes(nodes: list[Node]) -> list[dict[str, Any]]:
    return [
        {
            "key": n.key,
            "type": n.type.value,
            "title": n.title,
            **{
                k: n.body[k]
                for k in ("description", "acceptance_criteria", "steps", "method", "path")
                if k in n.body
            },
        }
        for n in nodes
    ]


def _gwt(subject: str) -> list[str]:
    s = subject.rstrip(".")
    return [
        f"Given a signed-in user with the right role, when they {s.lower()}, "
        "then the change is saved and confirmed",
        f"Given invalid or missing input, when they try to {s.lower()}, "
        "then a clear validation error is shown",
    ]


# ------------------------------------------------------------------ generative fixers


def fix_requirement_without_story(c: FixContext) -> str:
    req = c.node()
    goal = req.title[0].lower() + req.title[1:]

    def fallback() -> StoriesFix:
        return StoriesFix(
            stories=[
                NewStory(
                    title=f"As a user, I want {goal} so that my goal is met",
                    acceptance_criteria=_gwt(req.title),
                    test=NewTest(
                        title=f"E2E: {req.title}",
                        kind="e2e",
                        steps=["Sign in", "Perform the action", "Verify the outcome"],
                    ),
                )
            ]
        )

    out = c.llm(
        StoriesFix,
        f"Write 1-2 user stories that refine requirement {req.key}, each with "
        "2-4 Given/When/Then acceptance criteria and one test scenario.",
        _ctx_nodes([req]),
        fallback,
    )
    modules = c.of_type(T.module)
    for s in out.stories:
        story = c.add_node(T.story, s.title, {"acceptance_criteria": s.acceptance_criteria})
        c.link(req, story, E.refines)
        test = c.add_node(T.test, s.test.title, {"kind": s.test.kind, "steps": s.test.steps})
        c.link(story, test, E.verified_by)
        if modules:
            c.link(story, c.most_similar(story, modules), E.implemented_by)
    return f"Added {len(out.stories)} user stor{'y' if len(out.stories) == 1 else 'ies'} with tests"


def fix_story_without_test(c: FixContext) -> str:
    story = c.node()

    def fallback() -> TestsFix:
        return TestsFix(
            tests=[
                NewTest(
                    title=f"Verify: {story.title[:150]}",
                    kind="e2e",
                    steps=[str(x) for x in story.body.get("acceptance_criteria", [])][:4]
                    or ["Perform the story's main flow", "Verify the expected outcome"],
                )
            ]
        )

    out = c.llm(
        TestsFix,
        f"Write 1-2 test scenarios that verify story {story.key} against its acceptance criteria.",
        _ctx_nodes([story]),
        fallback,
    )
    for t in out.tests:
        test = c.add_node(T.test, t.title, {"kind": t.kind, "steps": t.steps})
        c.link(story, test, E.verified_by)
    return f"Added {len(out.tests)} test scenario(s)"


def fix_acceptance_criteria(c: FixContext) -> str:
    story = c.node()
    out = c.llm(
        CriteriaFix,
        f"Rewrite the acceptance criteria of story {story.key} as 2-4 "
        "concrete 'Given ..., when ..., then ...' statements.",
        _ctx_nodes([story]),
        lambda: CriteriaFix(acceptance_criteria=_gwt(story.title)),
    )
    story.body = {**story.body, "acceptance_criteria": out.acceptance_criteria}
    story.embedding = None
    c.changed.append(story.key)
    return "Rewrote acceptance criteria"


NFR_TEMPLATES = {
    "performance": (
        "Core API responds quickly",
        "p95 latency under 300 ms for the main endpoints at expected peak load.",
    ),
    "security": (
        "Data and access are protected",
        "Role-based access on every endpoint, TLS everywhere, secrets never logged.",
    ),
    "availability": (
        "Service stays available",
        "99.5% monthly uptime with health checks and automatic restarts.",
    ),
}


def fix_missing_nfr(c: FixContext) -> str:
    cat = str(c.issue.details.get("nfr", "performance"))
    title, desc = NFR_TEMPLATES.get(cat, NFR_TEMPLATES["performance"])

    def fallback() -> NfrFix:
        return NfrFix(
            title=title,
            description=desc,
            story=NewStory(
                title=f"As an operator, I want {title.lower()} so that users trust the product",
                acceptance_criteria=[
                    f"Given production traffic, when measured, then {desc[0].lower()}"
                    f"{desc[1:].rstrip('.')}",
                    "Given a regression, when it is detected, then the team is alerted",
                ],
                test=NewTest(
                    title=f"{cat.capitalize()} check",
                    kind="performance"
                    if cat == "performance"
                    else "security"
                    if cat == "security"
                    else "integration",
                    steps=["Set up the scenario", "Measure", "Compare with the target"],
                ),
            ),
        )

    out = c.llm(
        NfrFix,
        f"Write one measurable non-functional {cat} requirement for this project, "
        "one story for it and one test.",
        _ctx_nodes(c.of_type(T.requirement)),
        fallback,
    )
    req = c.add_node(
        T.requirement,
        out.title,
        {
            "kind": "non_functional",
            "nfr_category": cat,
            "description": out.description,
            "priority": "should",
        },
    )
    story = c.add_node(
        T.story, out.story.title, {"acceptance_criteria": out.story.acceptance_criteria}
    )
    c.link(req, story, E.refines)
    test = c.add_node(
        T.test, out.story.test.title, {"kind": out.story.test.kind, "steps": out.story.test.steps}
    )
    c.link(story, test, E.verified_by)
    modules = c.of_type(T.module)
    if modules:
        c.link(story, c.most_similar(story, modules), E.implemented_by)
    return f"Added a {cat} requirement with a story and test"


def fix_risk_mitigation(c: FixContext) -> str:
    risk = c.node()
    if len(str(risk.body.get("mitigation", "")).strip()) < 15:
        out = c.llm(
            MitigationFix,
            f"Write a concrete, specific mitigation for risk {risk.key}.",
            _ctx_nodes([risk]),
            lambda: MitigationFix(
                mitigation="Add monitoring and alerts for early detection, a documented "
                "fallback procedure, and an owner who reviews it each sprint."
            ),
        )
        risk.body = {**risk.body, "mitigation": out.mitigation}
        c.changed.append(risk.key)
    targets = c.of_type(T.requirement)
    linked = c.db.scalar(select(Edge.id).where(Edge.src_id == risk.id, Edge.type == E.threatens))
    if not linked and targets:
        c.link(risk, c.most_similar(risk, targets), E.threatens)
    return "Added mitigation / threatened requirement"


def _needs_human() -> RewriteFix:
    raise FixNotPossible(
        "Resolving a contradiction needs an AI provider or a human decision; "
        "edit one of the requirements, or dismiss the issue"
    )


def fix_contradiction(c: FixContext) -> str:
    a, b = c.node(0), c.node(1)
    out = c.llm(
        RewriteFix,
        f"Requirements {a.key} and {b.key} conflict. Rewrite {b.key} so both "
        f"can be true at once, keeping {b.key}'s intent. Explain the resolution in "
        "'rationale'.",
        _ctx_nodes([a, b]),
        _needs_human,
    )
    graph.update_node(
        c.db, b, user_id=None, title=out.title, body={**b.body, "description": out.description}
    )
    c.changed.append(b.key)
    return f"Rewrote {b.key}: {out.rationale}"[:300]


# ------------------------------------------------------------------ deterministic fixers


def _entity_for_path(c: FixContext, api: Node) -> Node | None:
    first = next(
        (
            s
            for s in str(api.body.get("path", "")).strip("/").split("/")
            if s and not s.startswith("{")
        ),
        "",
    )
    singular = re.sub(r"(ies)$", "y", re.sub(r"(?<!s)s$", "", first)).replace("-", "")
    for e in c.of_type(T.entity):
        if e.title.lower() == singular.lower():
            return e
    return None


def fix_api_links(c: FixContext) -> str:
    api = c.node()
    missing = c.issue.details.get("missing", ["module", "entity"])
    done = []
    if "module" in missing and c.of_type(T.module):
        mod = c.most_similar(api, c.of_type(T.module))
        c.link(mod, api, E.exposes)
        done.append(f"module {mod.key}")
    if "entity" in missing and c.of_type(T.entity):
        ent = _entity_for_path(c, api) or c.most_similar(api, c.of_type(T.entity))
        c.link(api, ent, E.persists)
        done.append(f"entity {ent.key}")
    return "Linked to " + " and ".join(done) if done else "Nothing to link"


# For an orphan of type X: (candidate parent type, edge type, parent is source?)
ORPHAN_LINKS: dict[NodeType, tuple[NodeType, EdgeType, bool]] = {
    T.story: (T.requirement, E.refines, True),
    T.module: (T.story, E.implemented_by, True),
    T.api: (T.module, E.exposes, True),
    T.entity: (T.api, E.persists, True),
    T.test: (T.story, E.verified_by, True),
    T.risk: (T.requirement, E.threatens, False),
}


def fix_orphan(c: FixContext) -> str:
    n = c.node()
    if n.type == T.requirement:
        return fix_requirement_without_story(c)
    parent_type, etype, parent_is_src = ORPHAN_LINKS[n.type]
    other = c.most_similar(n, [x for x in c.of_type(parent_type) if x.id != n.id])
    src, dst = (other, n) if parent_is_src else (n, other)
    if (src.type, dst.type) not in EDGE_RULES[etype]:
        raise FixNotPossible(f"Can't link {n.key} automatically")
    c.link(src, dst, etype)
    return f"Linked {n.key} to {other.key} ({etype.value})"


def fix_module_without_story(c: FixContext) -> str:
    mod = c.node()
    story = c.most_similar(mod, c.of_type(T.story))
    c.link(story, mod, E.implemented_by)
    return f"Linked {story.key} to {mod.key}"


def _plural(word: str) -> str:
    if word.endswith("y") and word[-2:-1] not in "aeiou":
        return word[:-1] + "ies"
    return word + ("es" if word.endswith(("s", "x", "ch", "sh")) else "s")


def _kebab(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "-", name).replace("_", "-").lower()


def fix_crud(c: FixContext) -> str:
    ent = c.node()
    apis = [
        c.nodes[e.src_id]
        for e in c.db.scalars(select(Edge).where(Edge.dst_id == ent.id, Edge.type == E.persists))
    ]
    base = "/" + _plural(_kebab(ent.title))
    for api in apis:
        p = str(api.body.get("path", ""))
        if p.count("/") == 1 and "{" not in p:
            base = p
            break
    owner = None
    for api in apis:
        exp = c.db.scalar(select(Edge).where(Edge.dst_id == api.id, Edge.type == E.exposes))
        if exp is not None:
            owner = c.nodes[exp.src_id]
            break
    owner = owner or (c.most_similar(ent, c.of_type(T.module)) if c.of_type(T.module) else None)
    wanted = {
        "create": ("POST", base),
        "read": ("GET", base + "/{id}"),
        "update": ("PATCH", base + "/{id}"),
        "delete": ("DELETE", base + "/{id}"),
    }
    added = []
    for op in c.issue.details.get("missing", list(CRUD)):
        method, path = wanted[op]
        low = ent.title[0].lower() + ent.title[1:]
        api = c.add_node(
            T.api,
            f"{method} {path}",
            {"method": method, "path": path, "summary": f"{op.capitalize()} {low}"},
        )
        c.link(api, ent, E.persists)
        if owner:
            c.link(owner, api, E.exposes)
        added.append(f"{method} {path}")
    return "Added " + ", ".join(added)


VERB_PREFIX = re.compile(
    r"^(create|get|update|delete|add|remove|fetch|list|make|set|edit|save|"
    r"insert|modify|do)[-_]?",
    re.IGNORECASE,
)


def normalise_path(path: str) -> str:
    out = []
    for seg in path.strip("/").split("/"):
        if not seg or re.fullmatch(r"v\d+", seg):
            continue
        if seg.startswith("{"):
            out.append("{" + re.sub(r"(?<!^)(?=[A-Z])", "_", seg.strip("{}")).lower() + "}")
            continue
        seg = VERB_PREFIX.sub("", seg)  # 'getOrders' -> 'Orders', 'create' -> ''
        seg = _kebab(seg).replace("--", "-").strip("-")
        if seg:
            out.append(seg)
    return "/" + "/".join(out)


def fix_api_naming(c: FixContext) -> str:
    api = c.node()
    old = str(api.body.get("path", ""))
    new = normalise_path(old)
    if new == old or path_problems(new):
        raise FixNotPossible(f"Couldn't derive a clean path from {old}; please rename it")
    api.body = {**api.body, "path": new}
    api.title = f"{api.body.get('method', 'GET')} {new}"
    api.embedding = None
    c.changed.append(api.key)
    return f"Renamed {old} -> {new}"


def fix_entity_naming(c: FixContext) -> str:
    ent = c.node()
    name = "".join(p[:1].upper() + p[1:] for p in re.split(r"[\s_-]+", ent.title) if p)
    if name.lower().endswith("ies"):
        name = name[:-3] + "y"
    elif name.lower().endswith("s") and not name.lower().endswith(("ss", "us", "is")):
        name = name[:-1]
    fields = []
    for f in ent.body.get("fields", []):
        fname = re.sub(r"(?<!^)(?=[A-Z])", "_", str(f.get("name", ""))).replace("-", "_").lower()
        fields.append({**f, "name": fname})
    pks = [f for f in fields if f.get("primary_key")]
    if not pks:
        fields.insert(0, {"name": "id", "type": "uuid", "primary_key": True, "nullable": False})
    elif len(pks) > 1:
        keep = next((f for f in pks if f["name"] == "id"), pks[0])
        for f in fields:
            f["primary_key"] = f is keep
    ent.title = name
    ent.body = {**ent.body, "fields": fields}
    ent.embedding = None
    c.changed.append(ent.key)
    return f"Normalised entity {name}"


def fix_duplicate(c: FixContext) -> str:
    keep, drop = c.node(0), c.node(1)
    moved = 0
    for e in list(
        c.db.scalars(select(Edge).where((Edge.src_id == drop.id) | (Edge.dst_id == drop.id)))
    ):
        src = keep.id if e.src_id == drop.id else e.src_id
        dst = keep.id if e.dst_id == drop.id else e.dst_id
        c.db.delete(e)
        c.db.flush()
        if src == dst:
            continue
        exists = c.db.scalar(
            select(Edge.id).where(Edge.src_id == src, Edge.dst_id == dst, Edge.type == e.type)
        )
        if not exists:
            c.db.add(
                Edge(
                    blueprint_id=keep.blueprint_id, src_id=src, dst_id=dst, type=e.type, body=e.body
                )
            )
            moved += 1
    c.db.delete(drop)
    c.nodes.pop(drop.id, None)
    c.db.flush()
    c.changed.append(keep.key)
    return f"Merged {drop.key} into {keep.key} ({moved} links moved)"


FIXERS: dict[str, Callable[[FixContext], str]] = {
    "TR-001": fix_requirement_without_story,
    "TR-002": fix_story_without_test,
    "TR-003": fix_api_links,
    "TR-004": fix_orphan,
    "TR-005": fix_module_without_story,
    "CP-001": fix_acceptance_criteria,
    "CP-002": fix_crud,
    "CP-003": fix_missing_nfr,
    "CP-004": fix_risk_mitigation,
    "CV-001": fix_api_naming,
    "CV-002": fix_entity_naming,
    "DUP-001": fix_duplicate,
    "DUP-002": fix_duplicate,
    "CON-001": fix_contradiction,
}


def apply_fix(
    db: Session,
    issue: Issue,
    report: Report = lambda s, p, e: None,
    *,
    providers: list[LLMProvider] | None = None,
    breaker: Breaker | None = None,
) -> dict[str, Any]:
    qr = db.get(QualityReport, issue.report_id)
    if qr is None:
        raise FixNotPossible("Issue's report no longer exists")
    blueprint = db.get(Blueprint, qr.blueprint_id)
    if blueprint is None:
        raise FixNotPossible("Blueprint no longer exists")
    fixer = FIXERS.get(issue.rule_code)
    if fixer is None:
        raise FixNotPossible(f"No automatic fix for {issue.rule_code}")
    nodes = {n.id: n for n in db.scalars(select(Node).where(Node.blueprint_id == blueprint.id))}
    ctx = FixContext(
        db,
        blueprint,
        issue,
        providers if providers is not None else default_providers(),
        breaker or RedisBreaker(),
        nodes,
    )
    report("fixing", 30, {"rule": issue.rule_code})
    score_before = blueprint.quality_score
    try:
        action = fixer(ctx)
        issue.resolved = True
        db.commit()
    except Exception:
        db.rollback()
        raise
    summary = run_verification(db, blueprint, report)
    return {
        "action": action,
        "provider": ctx.provider_used,
        "changed": ctx.changed,
        "score_before": score_before,
        "score_after": summary["score"],
        "report_id": summary["report_id"],
    }


# ------------------------------------------------------------------ regenerate subgraph


def regenerate_subgraph(
    db: Session,
    blueprint: Blueprint,
    root_id: uuid.UUID,
    report: Report = lambda s, p, e: None,
    *,
    providers: list[LLMProvider] | None = None,
    breaker: Breaker | None = None,
) -> dict[str, Any]:
    """Rewrite the stale nodes downstream of an edited node so they match it.
    Node ids, keys, links and delivery status are preserved."""
    root = db.get(Node, root_id)
    if root is None or root.blueprint_id != blueprint.id:
        raise FixNotPossible("Root node not found in this blueprint")
    impacted_ids = {r.node_id for r in graph.downstream_impact(db, root)}
    targets = (
        [n for n in db.scalars(select(Node).where(Node.id.in_(impacted_ids))) if n.stale]
        if impacted_ids
        else []
    )
    if not targets:
        return {"updated": [], "provider": "none", "message": "Nothing is stale"}
    report("regenerating", 30, {"targets": len(targets)})
    ctx = FixContext(
        db,
        blueprint,
        Issue(node_ids=[], details={}),
        providers if providers is not None else default_providers(),
        breaker or RedisBreaker(),
    )
    task = (
        f"{root.key} was just edited (new text below). Update each listed downstream item "
        "so it is consistent with the new version. Return one update per item, using its "
        "key. Keep items that are already consistent unchanged (repeat their title, use '' "
        "and [] for fields to keep)."
    )
    context = {"edited": _ctx_nodes([root])[0], "downstream": _ctx_nodes(targets)}
    out = ctx.llm(SubgraphUpdate, task, context, lambda: SubgraphUpdate(updates=[]))
    by_key = {n.key: n for n in targets}
    updated = []
    for u in out.updates:
        n = by_key.get(u.key)
        if n is None:
            continue
        n.title = u.title
        body = dict(n.body)
        if u.description:
            field_name = {T.module: "responsibility", T.api: "summary"}.get(n.type, "description")
            body[field_name] = u.description
        if u.acceptance_criteria and n.type == T.story:
            body["acceptance_criteria"] = u.acceptance_criteria
        if u.steps and n.type == T.test:
            body["steps"] = u.steps
        n.body = body
        n.embedding = None
        updated.append(n.key)
    for n in targets:
        n.stale = False  # reviewed: by the model, or acknowledged in demo mode
    db.commit()
    summary = run_verification(db, blueprint, report)
    return {
        "updated": updated,
        "reviewed": [n.key for n in targets],
        "provider": ctx.provider_used,
        "score_after": summary["score"],
    }

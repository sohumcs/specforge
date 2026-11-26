"""Deterministic rule layer.

Each rule is a small class with a code, category and severity. `check(graph)`
returns how many things it examined (`checks`) and the problems it found, each
pointing at the offending node ids and carrying a concrete fix hint. The score
uses `checks` as the denominator, so a rule that inspects 40 stories and finds
2 problems costs much less than one that inspects 2 and finds 2.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, ClassVar

from app.models.enums import EdgeType, IssueCategory, NodeType, Severity
from app.verify.graphview import GNode, GraphView

E, T, C, S = EdgeType, NodeType, IssueCategory, Severity


@dataclass
class Finding:
    rule_code: str
    category: IssueCategory
    severity: Severity
    message: str
    node_ids: list[Any]
    fix_hint: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class RuleResult:
    code: str
    category: IssueCategory
    checks: int
    findings: list[Finding]


class Rule:
    code: ClassVar[str]
    category: ClassVar[IssueCategory]
    severity: ClassVar[Severity]
    title: ClassVar[str]

    def check(self, g: GraphView) -> RuleResult:
        targets = list(self.targets(g))
        findings = [f for n in targets for f in self.inspect(g, n)]
        return RuleResult(self.code, self.category, len(targets), findings)

    def targets(self, g: GraphView) -> Iterable[GNode]:
        return []

    def inspect(self, g: GraphView, n: GNode) -> list[Finding]:
        return []

    def finding(
        self,
        message: str,
        nodes: list[GNode],
        fix_hint: str,
        *,
        severity: Severity | None = None,
        **details: Any,
    ) -> Finding:
        return Finding(
            self.code,
            self.category,
            severity or self.severity,
            message,
            [n.id for n in nodes],
            fix_hint,
            details,
        )


# ------------------------------------------------------------------ traceability


class RequirementHasStory(Rule):
    code, category, severity = "TR-001", C.traceability, S.high
    title = "Every requirement is refined by at least one user story"

    def targets(self, g: GraphView) -> Iterable[GNode]:
        return g.of_type(T.requirement)

    def inspect(self, g: GraphView, n: GNode) -> list[Finding]:
        if g.out(n.id, E.refines):
            return []
        return [
            self.finding(
                f"{n.key} has no user story",
                [n],
                "Generate a user story (with acceptance criteria) for it.",
            )
        ]


class StoryHasTest(Rule):
    code, category, severity = "TR-002", C.traceability, S.medium
    title = "Every user story is verified by at least one test"

    def targets(self, g: GraphView) -> Iterable[GNode]:
        return g.of_type(T.story)

    def inspect(self, g: GraphView, n: GNode) -> list[Finding]:
        if g.out(n.id, E.verified_by):
            return []
        return [
            self.finding(
                f"{n.key} has no test", [n], "Generate a test scenario that verifies this story."
            )
        ]


class ApiMapsToModuleAndEntity(Rule):
    code, category, severity = "TR-003", C.traceability, S.medium
    title = "Every API belongs to a module and touches at least one entity"

    def targets(self, g: GraphView) -> Iterable[GNode]:
        return g.of_type(T.api)

    def inspect(self, g: GraphView, n: GNode) -> list[Finding]:
        missing = []
        if not g.inc(n.id, E.exposes):
            missing.append("module")
        if not g.out(n.id, E.persists):
            missing.append("entity")
        if not missing:
            return []
        return [
            self.finding(
                f"{n.key} ({n.title}) has no {' or '.join(missing)}",
                [n],
                "Link it to the most relevant " + " and ".join(missing) + ".",
                missing=missing,
            )
        ]


class NoOrphans(Rule):
    code, category, severity = "TR-004", C.traceability, S.medium
    title = "No orphan nodes (every node is connected to the graph)"

    def targets(self, g: GraphView) -> Iterable[GNode]:
        return sorted(g.nodes.values(), key=lambda n: n.position)

    def inspect(self, g: GraphView, n: GNode) -> list[Finding]:
        if g.degree(n.id):
            return []
        return [
            self.finding(
                f"{n.key} ({n.type.value}) is not connected to anything",
                [n],
                "Link it to the most similar node it should trace to, or delete it.",
            )
        ]


class ModuleImplementsStory(Rule):
    code, category, severity = "TR-005", C.traceability, S.low
    title = "Every module implements at least one story"

    def targets(self, g: GraphView) -> Iterable[GNode]:
        return g.of_type(T.module)

    def inspect(self, g: GraphView, n: GNode) -> list[Finding]:
        if g.inc(n.id, E.implemented_by):
            return []
        return [
            self.finding(
                f"{n.key} ({n.title}) implements no user story",
                [n],
                "Link the stories this module delivers, or merge it into another.",
            )
        ]


# ------------------------------------------------------------------ completeness

GWT = re.compile(r"\bgiven\b.*\bwhen\b.*\bthen\b", re.IGNORECASE | re.DOTALL)


class StoryHasAcceptanceCriteria(Rule):
    code, category, severity = "CP-001", C.completeness, S.high
    title = "Every story has acceptance criteria in Given/When/Then form"

    def targets(self, g: GraphView) -> Iterable[GNode]:
        return g.of_type(T.story)

    def inspect(self, g: GraphView, n: GNode) -> list[Finding]:
        criteria = [c for c in n.body.get("acceptance_criteria", []) if str(c).strip()]
        if not criteria:
            return [
                self.finding(
                    f"{n.key} has no acceptance criteria",
                    [n],
                    "Write 2-4 Given/When/Then acceptance criteria.",
                )
            ]
        bad = [c for c in criteria if not GWT.search(str(c))]
        if bad:
            return [
                self.finding(
                    f"{n.key}: {len(bad)} acceptance criteria are not in Given/When/Then form",
                    [n],
                    "Rewrite them as 'Given <context>, when <action>, then <outcome>'.",
                    severity=S.low,
                    not_gwt=bad,
                )
            ]
        return []


CRUD = {"create": {"POST"}, "read": {"GET"}, "update": {"PUT", "PATCH"}, "delete": {"DELETE"}}


class EntityCrudCoverage(Rule):
    code, category, severity = "CP-002", C.completeness, S.low
    title = "Every entity has create/read/update/delete coverage (or an explicit exemption)"

    def targets(self, g: GraphView) -> Iterable[GNode]:
        return [n for n in g.of_type(T.entity) if not n.body.get("crud_exempt")]

    def inspect(self, g: GraphView, n: GNode) -> list[Finding]:
        methods = {g.nodes[e.src].body.get("method", "").upper() for e in g.inc(n.id, E.persists)}
        missing = [op for op, ms in CRUD.items() if not methods & ms]
        if not missing:
            return []
        return [
            self.finding(
                f"Entity {n.title} has no {'/'.join(missing)} endpoint",
                [n],
                "Add the missing endpoints, or mark the entity crud_exempt.",
                missing=missing,
            )
        ]


NFR_REQUIRED = ("performance", "security", "availability")


class NfrCoverage(Rule):
    code, category, severity = "CP-003", C.completeness, S.medium
    title = "Performance, security and availability requirements exist"

    def check(self, g: GraphView) -> RuleResult:
        reqs = g.of_type(T.requirement)
        present = {
            r.body.get("nfr_category") for r in reqs if r.body.get("kind") == "non_functional"
        }
        findings = [
            self.finding(
                f"No {cat} requirement",
                [],
                f"Add a measurable non-functional requirement for {cat}.",
                nfr=cat,
            )
            for cat in NFR_REQUIRED
            if cat not in present
        ]
        return RuleResult(self.code, self.category, len(NFR_REQUIRED), findings)


class HighRiskMitigated(Rule):
    code, category, severity = "CP-004", C.completeness, S.high
    title = "Every high risk has a concrete mitigation and threatens something"

    def targets(self, g: GraphView) -> Iterable[GNode]:
        return [
            r
            for r in g.of_type(T.risk)
            if "high" in (r.body.get("likelihood"), r.body.get("impact"))
        ]

    def inspect(self, g: GraphView, n: GNode) -> list[Finding]:
        problems = []
        if len(str(n.body.get("mitigation", "")).strip()) < 15:
            problems.append("no concrete mitigation")
        if not g.out(n.id, E.threatens):
            problems.append("not linked to the requirement or module it threatens")
        if not problems:
            return []
        return [
            self.finding(
                f"High risk {n.key}: {', '.join(problems)}",
                [n],
                "Write a specific mitigation and link the threatened items.",
                problems=problems,
            )
        ]


# ------------------------------------------------------------------ conventions

PATH_VERBS = {
    "create",
    "get",
    "update",
    "delete",
    "add",
    "remove",
    "fetch",
    "list",
    "make",
    "set",
    "edit",
    "save",
    "insert",
    "modify",
    "do",
}
KEBAB_SEGMENT = re.compile(r"^(\{[a-z][a-z0-9_]*\}|[a-z0-9]+(-[a-z0-9]+)*)$")


def path_problems(path: str) -> list[str]:
    problems = []
    segments = [s for s in path.strip("/").split("/") if s]
    for seg in segments:
        if seg.startswith("{"):
            if not KEBAB_SEGMENT.match(seg):
                problems.append(f"path parameter '{seg}' should be snake_case in braces")
            continue
        if not KEBAB_SEGMENT.match(seg):
            problems.append(f"segment '{seg}' should be lowercase kebab-case")
        words = set(re.split(r"[-_]", seg.lower())) | {re.sub(r"[A-Z].*", "", seg).lower()}
        if words & PATH_VERBS:
            problems.append(f"segment '{seg}' contains a verb; use HTTP methods instead")
    if re.search(r"/v\d+(/|$)", path):
        problems.append("version prefix belongs in the base URL, not each path")
    return problems


class ApiNaming(Rule):
    code, category, severity = "CV-001", C.conventions, S.low
    title = "REST paths: lowercase kebab-case nouns, no verbs"

    def targets(self, g: GraphView) -> Iterable[GNode]:
        return g.of_type(T.api)

    def inspect(self, g: GraphView, n: GNode) -> list[Finding]:
        problems = path_problems(str(n.body.get("path", "")))
        if not problems:
            return []
        return [
            self.finding(
                f"{n.key} {n.title}: {problems[0]}",
                [n],
                "Rename the path to a noun-based, kebab-case resource path.",
                problems=problems,
            )
        ]


PASCAL = re.compile(r"^[A-Z][a-zA-Z0-9]*$")
SNAKE = re.compile(r"^[a-z][a-z0-9_]*$")
SINGULAR_EXCEPTIONS = ("ss", "us", "is", "news", "series", "status", "analytics")


class EntityNaming(Rule):
    code, category, severity = "CV-002", C.conventions, S.low
    title = "Entities: PascalCase singular names, snake_case fields, exactly one primary key"

    def targets(self, g: GraphView) -> Iterable[GNode]:
        return g.of_type(T.entity)

    def inspect(self, g: GraphView, n: GNode) -> list[Finding]:
        problems = []
        name = n.title
        if not PASCAL.match(name):
            problems.append(f"name '{name}' should be PascalCase")
        elif name.lower().endswith("s") and not name.lower().endswith(SINGULAR_EXCEPTIONS):
            problems.append(f"name '{name}' looks plural")
        fields = n.body.get("fields", [])
        bad_fields = [f.get("name", "") for f in fields if not SNAKE.match(f.get("name", ""))]
        if bad_fields:
            problems.append(f"fields not snake_case: {', '.join(bad_fields)}")
        pks = [f for f in fields if f.get("primary_key")]
        if len(pks) != 1:
            problems.append(f"has {len(pks)} primary keys (expected 1)")
        if not problems:
            return []
        return [
            self.finding(
                f"Entity {name}: {problems[0]}",
                [n],
                "Normalise the entity name and fields.",
                problems=problems,
            )
        ]


KEY = re.compile(r"^[A-Z]{2,4}-\d{3,5}$")


class KeysWellFormed(Rule):
    code, category, severity = "CV-003", C.conventions, S.low
    title = "Node keys are well-formed (REQ-001, US-002, ...)"

    def targets(self, g: GraphView) -> Iterable[GNode]:
        return sorted(g.nodes.values(), key=lambda n: n.position)

    def inspect(self, g: GraphView, n: GNode) -> list[Finding]:
        if KEY.match(n.key):
            return []
        return [self.finding(f"Key '{n.key}' is malformed", [n], "Use PREFIX-NNN keys.")]


ALL_RULES: list[Rule] = [
    RequirementHasStory(),
    StoryHasTest(),
    ApiMapsToModuleAndEntity(),
    NoOrphans(),
    ModuleImplementsStory(),
    StoryHasAcceptanceCriteria(),
    EntityCrudCoverage(),
    NfrCoverage(),
    HighRiskMitigated(),
    ApiNaming(),
    EntityNaming(),
    KeysWellFormed(),
]


def run_rules(g: GraphView, rules: list[Rule] | None = None) -> list[RuleResult]:
    return [rule.check(g) for rule in (rules or ALL_RULES)]


RULE_CATALOG = {
    r.code: {"title": r.title, "category": r.category.value, "severity": r.severity.value}
    for r in ALL_RULES
}

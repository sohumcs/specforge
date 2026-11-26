"""Run the two-layer verification and persist a QualityReport.

    rule_check  deterministic rules on a GraphView snapshot          (app/verify/rules.py)
    ml_check    embeddings -> pgvector duplicate search,
                NLI + polarity cue -> contradictions                (app/verify/ml.py)
    scoring     weighted 0-100 score + per-category breakdown       (app/verify/scoring.py)

Graceful degradation: if the ML models can't be loaded, the report is still
produced from the rule layer and is flagged `ml: "unavailable"`; it never fails
the job.
"""

import logging
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Blueprint, Edge, Issue, Node, QualityReport
from app.models.enums import IssueCategory, NodeType, Severity
from app.verify import ml
from app.verify.graphview import GEdge, GNode, GraphView
from app.verify.rules import Finding, RuleResult, run_rules
from app.verify.scoring import score

log = logging.getLogger("specforge.verify")
Report = Callable[[str, int, dict[str, Any]], None]

# Node types compared for duplicates. Tests are excluded: scenarios for related
# stories are legitimately similar ("valid login" / "invalid login").
DUPLICATE_TYPES = [
    NodeType.requirement,
    NodeType.story,
    NodeType.module,
    NodeType.api,
    NodeType.entity,
    NodeType.risk,
]


def snapshot(db: Session, blueprint_id: uuid.UUID) -> tuple[GraphView, list[Node]]:
    nodes = list(
        db.scalars(select(Node).where(Node.blueprint_id == blueprint_id).order_by(Node.position))
    )
    edges = db.scalars(select(Edge).where(Edge.blueprint_id == blueprint_id))
    g = GraphView.build(
        [GNode(n.id, n.type, n.key, n.title, n.body, n.position) for n in nodes],
        [GEdge(e.src_id, e.dst_id, e.type) for e in edges],
    )
    return g, nodes


def embedding_text(node: Node) -> str:
    return GNode(node.id, node.type, node.key, node.title, node.body).text()


def ensure_embeddings(db: Session, nodes: list[Node]) -> int:
    """Embed every node whose embedding is missing (new or edited). Returns count."""
    todo = [n for n in nodes if n.embedding is None]
    if not todo:
        return 0
    vectors = ml.embed([embedding_text(n) for n in todo])
    for node, vec in zip(todo, vectors, strict=True):
        node.embedding = vec.tolist()
    db.commit()
    return len(todo)


_DUP_SQL = text(
    """
    SELECT a.id AS a_id, b.id AS b_id, 1 - (a.embedding <=> b.embedding) AS similarity
    FROM nodes a
    JOIN nodes b
      ON b.blueprint_id = a.blueprint_id AND b.type = a.type AND a.id < b.id
    WHERE a.blueprint_id = :bp
      AND a.type::text = ANY(:types)
      AND a.embedding IS NOT NULL AND b.embedding IS NOT NULL
      AND 1 - (a.embedding <=> b.embedding) >= :min_sim
    ORDER BY similarity DESC
    """
)


def duplicate_findings(db: Session, blueprint_id: uuid.UUID, g: GraphView) -> list[Finding]:
    rows = db.execute(
        _DUP_SQL,
        {
            "bp": blueprint_id,
            "types": [t.value for t in DUPLICATE_TYPES],
            "min_sim": ml.NEAR_DUPLICATE_MIN,
        },
    ).all()
    findings = []
    for row in rows:
        a, b = g.nodes[row.a_id], g.nodes[row.b_id]
        first, second = sorted((a, b), key=lambda n: n.position)
        sim = round(float(row.similarity), 3)
        hard = sim >= ml.DUPLICATE_MIN
        findings.append(
            Finding(
                rule_code="DUP-001" if hard else "DUP-002",
                category=IssueCategory.uniqueness,
                severity=Severity.medium if hard else Severity.low,
                message=(
                    f"{first.key} and {second.key} are "
                    f"{'duplicates' if hard else 'near-duplicates'} (similarity {sim:.2f})"
                ),
                node_ids=[first.id, second.id],
                fix_hint=f"Merge {second.key} into {first.key}, keeping all of its links.",
                details={"similarity": sim, "texts": [first.text(), second.text()]},
            )
        )
    return findings


def contradiction_findings(g: GraphView, nodes: list[Node]) -> list[Finding]:
    reqs = [n for n in nodes if n.type == NodeType.requirement and n.embedding is not None]
    if len(reqs) < 2:
        return []
    import numpy as np

    texts = [embedding_text(n) for n in reqs]
    vectors = np.asarray([n.embedding for n in reqs], dtype=np.float32)
    findings = []
    for c in ml.find_contradictions(texts, vectors):
        a, b = reqs[c.a], reqs[c.b]
        findings.append(
            Finding(
                rule_code="CON-001",
                category=IssueCategory.consistency,
                severity=Severity.high,
                message=f"{a.key} and {b.key} may contradict each other ({c.cue})",
                node_ids=[a.id, b.id],
                fix_hint=f"Rewrite {b.key} so it is consistent with {a.key} (or vice versa).",
                details={
                    "nli_contradiction": c.score,
                    "similarity": c.similarity,
                    "cue": c.cue,
                    "texts": [texts[c.a], texts[c.b]],
                },
            )
        )
    return findings


def fingerprint(rule_code: str, node_ids: list[Any]) -> str:
    """Stable identity of an issue across re-verifications (for dismissals)."""
    return rule_code + ":" + ",".join(sorted(str(i) for i in node_ids))


FIXABLE = {
    "TR-001",
    "TR-002",
    "TR-003",
    "TR-004",
    "TR-005",
    "CP-001",
    "CP-002",
    "CP-003",
    "CP-004",
    "CV-001",
    "CV-002",
    "DUP-001",
    "DUP-002",
    "CON-001",
}


def run_verification(
    db: Session, blueprint: Blueprint, report: Report = lambda s, p, e: None
) -> dict[str, Any]:
    report("rule_check", 88, {})
    g, nodes = snapshot(db, blueprint.id)
    rule_results = run_rules(g)

    report("ml_check", 92, {})
    ml_findings: list[Finding] = []
    ml_status = "ok"
    try:
        embedded = ensure_embeddings(db, nodes)
        ml_findings = duplicate_findings(db, blueprint.id, g) + contradiction_findings(g, nodes)
    except Exception:
        db.rollback()
        log.exception("ML verification unavailable for blueprint %s", blueprint.id)
        ml_status, embedded = "unavailable", 0

    report("scoring", 97, {})
    dismissed = set(blueprint.settings.get("dismissed_issues", []))

    def keep(f: Finding) -> bool:
        return fingerprint(f.rule_code, f.node_ids) not in dismissed

    scored_rules = [
        RuleResult(r.code, r.category, r.checks, [f for f in r.findings if keep(f)])
        for r in rule_results
    ]
    overall, categories = score(scored_rules, [f for f in ml_findings if keep(f)])
    breakdown = {
        "categories": [
            {
                "category": c.category.value,
                "score": c.score,
                "weight": c.weight,
                "checks": c.checks,
                "issues": c.issues,
            }
            for c in categories
        ],
        "rules": [
            {
                "code": r.code,
                "category": r.category.value,
                "checks": r.checks,
                "violations": len(r.findings),
            }
            for r in rule_results
        ],
        "ml": ml_status,
        "embedded_nodes": embedded,
        "node_count": len(nodes),
    }
    qr = QualityReport(blueprint_id=blueprint.id, score=overall, breakdown=breakdown)
    db.add(qr)
    db.flush()
    findings = [f for r in rule_results for f in r.findings] + ml_findings
    for f in findings:
        fp = fingerprint(f.rule_code, f.node_ids)
        db.add(
            Issue(
                report_id=qr.id,
                rule_code=f.rule_code,
                category=f.category,
                severity=f.severity,
                message=f.message,
                node_ids=list(f.node_ids),
                fix_hint=f.fix_hint,
                resolved=fp in dismissed,
                details={**f.details, "fixable": f.rule_code in FIXABLE, "fingerprint": fp},
            )
        )
    blueprint.quality_score = overall
    db.commit()
    log.info(
        "blueprint %s verified: score %d, %d issues (ml=%s)",
        blueprint.id,
        overall,
        len(findings),
        ml_status,
    )
    return {
        "score": overall,
        "issues": len(findings),
        "report_id": str(qr.id),
        "ml": ml_status,
        "categories": {c.category.value: c.score for c in categories},
    }

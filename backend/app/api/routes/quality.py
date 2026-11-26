"""Quality: verify, read the score + issues, fix / dismiss issues, regenerate a
stale subgraph, and semantic "similar nodes" search (pgvector HNSW)."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel
from sqlalchemy import select, text

from app.api.deps import DB, CurrentUser
from app.api.routes.jobs import get_enqueuer, submit_job
from app.core.errors import AppError, Conflict, NotFound
from app.models import Blueprint, Issue, Node, QualityReport
from app.models.enums import IssueCategory, JobKind, Role
from app.services import jobs as job_service
from app.services.access import authorize_blueprint, authorize_node
from app.services.verification import fingerprint
from app.verify.rules import RULE_CATALOG, Finding, RuleResult
from app.verify.scoring import score

router = APIRouter(tags=["quality"])

Enqueuer = Annotated[job_service.Enqueue, Depends(get_enqueuer)]
IdemKey = Annotated[str | None, Header(max_length=100)]

RULE_EXTRAS = {
    "DUP-001": {
        "title": "No duplicate items (embedding similarity >= 0.90)",
        "category": "uniqueness",
        "severity": "medium",
    },
    "DUP-002": {
        "title": "No near-duplicate items (similarity 0.80-0.90)",
        "category": "uniqueness",
        "severity": "low",
    },
    "CON-001": {
        "title": "No contradictory requirements (NLI + polarity cue)",
        "category": "consistency",
        "severity": "high",
    },
}


@router.get("/rules")
def rules_catalog() -> dict[str, Any]:
    return {**RULE_CATALOG, **RULE_EXTRAS}


def latest_report(db: DB, blueprint_id: uuid.UUID) -> QualityReport | None:
    return db.scalar(
        select(QualityReport)
        .where(QualityReport.blueprint_id == blueprint_id)
        .order_by(QualityReport.created_at.desc())
        .limit(1)
    )


def issue_out(issue: Issue, keys: dict[uuid.UUID, str]) -> dict[str, Any]:
    return {
        "id": str(issue.id),
        "rule_code": issue.rule_code,
        "category": issue.category.value,
        "severity": issue.severity.value,
        "message": issue.message,
        "fix_hint": issue.fix_hint,
        "node_ids": [str(n) for n in issue.node_ids],
        "node_keys": [keys.get(n, "(deleted)") for n in issue.node_ids],
        "resolved": issue.resolved,
        "fixable": bool(issue.details.get("fixable")),
        "details": {k: v for k, v in issue.details.items() if k not in ("fixable",)},
    }


@router.post("/blueprints/{blueprint_id}/verify", status_code=202)
def verify(
    blueprint_id: uuid.UUID,
    request: Request,
    db: DB,
    user: CurrentUser,
    enqueue: Enqueuer,
    idempotency_key: IdemKey = None,
) -> Any:
    bp = authorize_blueprint(db, user, blueprint_id, Role.editor)
    return submit_job(db, user, request, bp, JobKind.verify, {}, idempotency_key, enqueue)


@router.get("/blueprints/{blueprint_id}/quality")
def get_quality(
    blueprint_id: uuid.UUID, db: DB, user: CurrentUser, include_resolved: bool = Query(True)
) -> dict[str, Any]:
    authorize_blueprint(db, user, blueprint_id, Role.viewer)
    qr = latest_report(db, blueprint_id)
    if qr is None:
        raise NotFound("This blueprint hasn't been verified yet", code="NOT_VERIFIED")
    keys = dict(
        db.execute(select(Node.id, Node.key).where(Node.blueprint_id == blueprint_id))
        .tuples()
        .all()
    )
    issues = [i for i in qr.issues if include_resolved or not i.resolved]
    severity_rank = {"high": 0, "medium": 1, "low": 2}
    issues.sort(key=lambda i: (i.resolved, severity_rank[i.severity.value], i.rule_code))
    return {
        "report_id": str(qr.id),
        "score": qr.score,
        "created_at": qr.created_at,
        "breakdown": qr.breakdown,
        "issues": [issue_out(i, keys) for i in issues],
    }


@router.get("/blueprints/{blueprint_id}/quality/history")
def quality_history(blueprint_id: uuid.UUID, db: DB, user: CurrentUser) -> list[dict[str, Any]]:
    authorize_blueprint(db, user, blueprint_id, Role.viewer)
    rows = db.scalars(
        select(QualityReport)
        .where(QualityReport.blueprint_id == blueprint_id)
        .order_by(QualityReport.created_at.desc())
        .limit(30)
    )
    return [{"report_id": str(r.id), "score": r.score, "created_at": r.created_at} for r in rows]


def _issue_and_blueprint(
    db: DB, user: CurrentUser, issue_id: uuid.UUID, role: Role
) -> tuple[Issue, Blueprint, QualityReport]:
    issue = db.get(Issue, issue_id)
    if issue is None:
        raise NotFound("Issue not found")
    qr = db.get(QualityReport, issue.report_id)
    if qr is None:
        raise NotFound("Issue not found")
    bp = authorize_blueprint(db, user, qr.blueprint_id, role)
    return issue, bp, qr


@router.post("/issues/{issue_id}/fix", status_code=202)
def fix_issue(
    issue_id: uuid.UUID,
    request: Request,
    db: DB,
    user: CurrentUser,
    enqueue: Enqueuer,
    idempotency_key: IdemKey = None,
) -> Any:
    issue, bp, qr = _issue_and_blueprint(db, user, issue_id, Role.editor)
    if latest_report(db, bp.id) is not qr:
        raise Conflict("This issue is from an older report; re-verify first", code="STALE_ISSUE")
    if not issue.details.get("fixable"):
        raise AppError(f"{issue.rule_code} has no automatic fix", code="NOT_FIXABLE")
    if issue.resolved:
        raise Conflict("Issue is already resolved", code="ALREADY_RESOLVED")
    return submit_job(
        db,
        user,
        request,
        bp,
        JobKind.fix_issue,
        {"issue_id": str(issue.id)},
        idempotency_key,
        enqueue,
    )


def rescore(db: DB, qr: QualityReport) -> int:
    """Recompute a report's score from its stored issues, skipping resolved ones.
    Instant (no ML): rule check counts come from the stored breakdown."""
    open_issues = [i for i in qr.issues if not i.resolved]

    def finding(i: Issue) -> Finding:
        return Finding(i.rule_code, i.category, i.severity, i.message, list(i.node_ids), i.fix_hint)

    rule_results = [
        RuleResult(
            r["code"],
            IssueCategory(RULE_CATALOG[r["code"]]["category"]),
            r["checks"],
            [finding(i) for i in open_issues if i.rule_code == r["code"]],
        )
        for r in qr.breakdown.get("rules", [])
        if r["code"] in RULE_CATALOG
    ]
    ml = [finding(i) for i in open_issues if i.rule_code in RULE_EXTRAS]
    overall, cats = score(rule_results, ml)
    qr.score = overall
    qr.breakdown = {
        **qr.breakdown,
        "categories": [
            {
                "category": c.category.value,
                "score": c.score,
                "weight": c.weight,
                "checks": c.checks,
                "issues": c.issues,
            }
            for c in cats
        ],
    }
    return overall


def _set_dismissed(db: DB, user: CurrentUser, issue_id: uuid.UUID, dismissed: bool) -> Any:
    issue, bp, qr = _issue_and_blueprint(db, user, issue_id, Role.editor)
    fp = fingerprint(issue.rule_code, list(issue.node_ids))
    current = set(bp.settings.get("dismissed_issues", []))
    current = current | {fp} if dismissed else current - {fp}
    bp.settings = {**bp.settings, "dismissed_issues": sorted(current)}
    issue.resolved = dismissed
    new_score = rescore(db, qr)
    if latest_report(db, bp.id) is qr:
        bp.quality_score = new_score
    db.commit()
    return {"issue_id": str(issue.id), "resolved": issue.resolved, "score": new_score}


@router.post("/issues/{issue_id}/dismiss")
def dismiss_issue(issue_id: uuid.UUID, db: DB, user: CurrentUser) -> Any:
    """Mark an issue as 'not a problem'. Remembered across re-verifications."""
    return _set_dismissed(db, user, issue_id, True)


@router.post("/issues/{issue_id}/restore")
def restore_issue(issue_id: uuid.UUID, db: DB, user: CurrentUser) -> Any:
    return _set_dismissed(db, user, issue_id, False)


class RegenerateIn(BaseModel):
    root_node_id: uuid.UUID


@router.post("/blueprints/{blueprint_id}/regenerate-subgraph", status_code=202)
def regenerate(
    blueprint_id: uuid.UUID,
    body: RegenerateIn,
    request: Request,
    db: DB,
    user: CurrentUser,
    enqueue: Enqueuer,
    idempotency_key: IdemKey = None,
) -> Any:
    bp = authorize_blueprint(db, user, blueprint_id, Role.editor)
    root = db.get(Node, body.root_node_id)
    if root is None or root.blueprint_id != bp.id:
        raise NotFound("Node not found in this blueprint")
    return submit_job(
        db,
        user,
        request,
        bp,
        JobKind.regenerate_subgraph,
        {"root_node_id": str(root.id)},
        idempotency_key,
        enqueue,
    )


_SIMILAR_SQL = text(
    """
    SELECT id, key, type::text AS type, title,
           1 - (embedding <=> CAST(:vec AS vector)) AS similarity
    FROM nodes
    WHERE blueprint_id = :bp AND id <> :id AND embedding IS NOT NULL
    ORDER BY embedding <=> CAST(:vec AS vector)
    LIMIT :k
    """
)


@router.get("/nodes/{node_id}/similar")
def similar_nodes(
    node_id: uuid.UUID, db: DB, user: CurrentUser, k: int = Query(5, ge=1, le=20)
) -> list[dict[str, Any]]:
    """Nearest neighbours by embedding (cosine), served by the HNSW index."""
    node = authorize_node(db, user, node_id, Role.viewer)
    if node.embedding is None:
        raise Conflict("Node has no embedding yet; run verification first", code="NOT_EMBEDDED")
    vec = "[" + ",".join(f"{x:.6f}" for x in node.embedding) + "]"
    rows = db.execute(
        _SIMILAR_SQL, {"vec": vec, "bp": node.blueprint_id, "id": node.id, "k": k}
    ).all()
    return [
        {
            "id": str(r.id),
            "key": r.key,
            "type": r.type,
            "title": r.title,
            "similarity": round(float(r.similarity), 3),
        }
        for r in rows
    ]

"""Delivery roll-ups: how much of each requirement / module is done.

Work items are stories and tests (the only nodes with a delivery status).
A requirement's work = its stories + the tests verifying them; a module's work
= the stories it implements + their tests. Percent = done / total.
"""

import uuid
from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from app.models.enums import EdgeType, NodeStatus, NodeType
from app.services.verification import snapshot
from app.verify.graphview import GNode, GraphView

E, T = EdgeType, NodeType
STATUSES = [s.value for s in NodeStatus]


def _summary(items: list[GNode], status: dict[uuid.UUID, str]) -> dict[str, Any]:
    counts = Counter(status[n.id] for n in items)
    total = len(items)
    done = counts.get(NodeStatus.done.value, 0)
    return {
        "total": total,
        "done": done,
        "percent": round(100 * done / total) if total else 0,
        "by_status": {s: counts.get(s, 0) for s in STATUSES},
    }


def _work_for_stories(g: GraphView, stories: list[GNode]) -> list[GNode]:
    tests: dict[uuid.UUID, GNode] = {}
    for s in stories:
        for e in g.out(s.id, E.verified_by):
            tests[e.dst] = g.nodes[e.dst]
    return stories + list(tests.values())


def rollups(db: Session, blueprint_id: uuid.UUID) -> dict[str, Any]:
    g, nodes = snapshot(db, blueprint_id)
    status = {n.id: n.status.value for n in nodes}

    def row(n: GNode, stories: list[GNode]) -> dict[str, Any]:
        return {
            "id": str(n.id),
            "key": n.key,
            "title": n.title,
            **_summary(_work_for_stories(g, stories), status),
        }

    requirements = [
        row(r, [g.nodes[e.dst] for e in g.out(r.id, E.refines)]) for r in g.of_type(T.requirement)
    ]
    modules = [
        row(m, [g.nodes[e.src] for e in g.inc(m.id, E.implemented_by)]) for m in g.of_type(T.module)
    ]
    work = g.of_type(T.story) + g.of_type(T.test)
    return {
        "overall": _summary(work, status),
        "stories": _summary(g.of_type(T.story), status),
        "tests": _summary(g.of_type(T.test), status),
        "requirements": requirements,
        "modules": modules,
    }

"""Blueprint graph: node/edge writes, trace queries and change-impact propagation.

Direction convention
--------------------
Edges point "downstream", from the thing that causes work to the thing that
does it: requirement -refines-> story -implemented_by-> module -exposes-> api
-persists-> entity, and story|api -verified_by-> test.

Two edge types point the other way relative to impact:
* risk -threatens-> requirement: changing the requirement affects the risk.
* module A -depends_on-> module B: changing B affects A.
For these we walk the edge backwards (dst -> src) when computing impact.
`relates_to` (entity <-> entity) is not followed, or one schema tweak would
mark half the blueprint stale.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, Conflict, NotFound
from app.models import Blueprint, ChangeEvent, Edge, Node
from app.models.enums import (
    EDGE_RULES,
    NODE_KEY_PREFIX,
    TRACKABLE_TYPES,
    EdgeType,
    NodeStatus,
    NodeType,
)

IMPACT_FORWARD = [
    EdgeType.refines,
    EdgeType.implemented_by,
    EdgeType.exposes,
    EdgeType.persists,
    EdgeType.verified_by,
]
IMPACT_REVERSE = [EdgeType.threatens, EdgeType.depends_on]


@dataclass(frozen=True)
class Reached:
    node_id: uuid.UUID
    depth: int


# Recursive walk over a directed view of the blueprint's edges.
# `path` holds every node on the current branch, so cycles are cut;
# `max_depth` bounds the walk even on pathological graphs.
_WALK_SQL = text(
    """
    WITH RECURSIVE
    directed(src, dst) AS (
        SELECT e.src_id, e.dst_id FROM edges e
        WHERE e.blueprint_id = :bp AND e.type::text = ANY(:fwd)
        UNION ALL
        SELECT e.dst_id, e.src_id FROM edges e
        WHERE e.blueprint_id = :bp AND e.type::text = ANY(:rev)
    ),
    walk(node_id, depth, path) AS (
        SELECT CAST(:root AS uuid), 0, ARRAY[CAST(:root AS uuid)]
        UNION ALL
        SELECT d.dst, w.depth + 1, w.path || d.dst
        FROM walk w
        JOIN directed d ON d.src = w.node_id
        WHERE w.depth < :max_depth AND NOT d.dst = ANY(w.path)
    )
    SELECT node_id, MIN(depth) AS depth
    FROM walk
    WHERE depth > 0
    GROUP BY node_id
    ORDER BY MIN(depth), node_id
    """
)


def _walk(
    db: Session,
    blueprint_id: uuid.UUID,
    root_id: uuid.UUID,
    forward: list[EdgeType],
    reverse: list[EdgeType],
) -> list[Reached]:
    rows = db.execute(
        _WALK_SQL,
        {
            "bp": blueprint_id,
            "root": root_id,
            "fwd": [e.value for e in forward],
            "rev": [e.value for e in reverse],
            "max_depth": get_settings().max_graph_depth,
        },
    ).all()
    return [Reached(node_id=r.node_id, depth=r.depth) for r in rows]


def downstream_impact(db: Session, node: Node) -> list[Reached]:
    """Everything that may need rework if `node` changes."""
    return _walk(db, node.blueprint_id, node.id, IMPACT_FORWARD, IMPACT_REVERSE)


def upstream_trace(db: Session, node: Node) -> list[Reached]:
    """Everything `node` exists because of (the reverse of impact)."""
    return _walk(db, node.blueprint_id, node.id, IMPACT_REVERSE, IMPACT_FORWARD)


def describe(db: Session, reached: list[Reached]) -> list[dict[str, Any]]:
    if not reached:
        return []
    nodes = {
        n.id: n for n in db.scalars(select(Node).where(Node.id.in_([r.node_id for r in reached])))
    }
    return [
        {
            "id": r.node_id,
            "key": nodes[r.node_id].key,
            "type": nodes[r.node_id].type,
            "title": nodes[r.node_id].title,
            "depth": r.depth,
        }
        for r in reached
        if r.node_id in nodes
    ]


def impact_payload(db: Session, node: Node, reached: list[Reached]) -> dict[str, Any]:
    by_depth: dict[int, list[uuid.UUID]] = defaultdict(list)
    for r in reached:
        by_depth[r.depth].append(r.node_id)
    return {"root_id": node.id, "impacted": describe(db, reached), "by_depth": dict(by_depth)}


# ----------------------------------------------------------------------------- writes


def next_key(db: Session, blueprint_id: uuid.UUID, node_type: NodeType) -> str:
    prefix = NODE_KEY_PREFIX[node_type]
    keys = db.scalars(
        select(Node.key).where(Node.blueprint_id == blueprint_id, Node.key.like(f"{prefix}-%"))
    ).all()
    highest = max((int(k.split("-")[1]) for k in keys if k.split("-")[1].isdigit()), default=0)
    return f"{prefix}-{highest + 1:03d}"


def create_node(
    db: Session,
    blueprint: Blueprint,
    *,
    node_type: NodeType,
    title: str,
    body: dict[str, Any],
    key: str | None = None,
) -> Node:
    key = key or next_key(db, blueprint.id, node_type)
    if db.scalar(select(Node.id).where(Node.blueprint_id == blueprint.id, Node.key == key)):
        raise Conflict(f"Key {key} already exists in this blueprint", code="DUPLICATE_KEY")
    position = db.scalar(
        select(func.coalesce(func.max(Node.position), 0) + 1).where(
            Node.blueprint_id == blueprint.id
        )
    )
    node = Node(
        blueprint_id=blueprint.id,
        type=node_type,
        key=key,
        title=title,
        body=body,
        position=position or 1,
    )
    db.add(node)
    db.commit()
    return node


def update_node(
    db: Session,
    node: Node,
    *,
    user_id: uuid.UUID | None,
    title: str | None,
    body: dict[str, Any] | None,
) -> list[Reached]:
    """Edit a node's content and, in the SAME transaction, mark everything
    downstream as stale and record a change event. Returns the impact set."""
    before = {"title": node.title, "body": node.body}
    changed = (title is not None and title != node.title) or (
        body is not None and body != node.body
    )
    if title is not None:
        node.title = title
    if body is not None:
        node.body = body
    if not changed:
        db.commit()
        return []

    node.embedding = None  # content changed -> embedding must be recomputed
    reached = downstream_impact(db, node)
    impacted_ids = [r.node_id for r in reached]
    if impacted_ids:
        for n in db.scalars(select(Node).where(Node.id.in_(impacted_ids))):
            n.stale = True
    node.stale = False
    db.add(
        ChangeEvent(
            blueprint_id=node.blueprint_id,
            node_id=node.id,
            user_id=user_id,
            before=before,
            after={"title": node.title, "body": node.body},
            impacted=impacted_ids,
        )
    )
    db.commit()
    return reached


def set_status(db: Session, node: Node, status: NodeStatus) -> Node:
    if node.type not in TRACKABLE_TYPES:
        raise AppError(
            "Only stories and tests have a delivery status",
            code="NOT_TRACKABLE",
            details={"type": node.type.value},
        )
    node.status = status
    db.commit()
    return node


def delete_node(db: Session, node: Node) -> None:
    db.delete(node)  # edges cascade at the database level
    db.commit()


def validate_edge(src: Node, dst: Node, edge_type: EdgeType) -> None:
    if src.blueprint_id != dst.blueprint_id:
        raise AppError("Both nodes must belong to the same blueprint", code="CROSS_BLUEPRINT_EDGE")
    if src.id == dst.id:
        raise AppError("A node cannot link to itself", code="SELF_LOOP")
    if (src.type, dst.type) not in EDGE_RULES[edge_type]:
        allowed = sorted(f"{a.value}->{b.value}" for a, b in EDGE_RULES[edge_type])
        raise AppError(
            f"'{edge_type.value}' cannot connect {src.type.value} to {dst.type.value}",
            code="INVALID_EDGE",
            details={"allowed": allowed},
        )


def create_edge(
    db: Session,
    blueprint: Blueprint,
    *,
    src_id: uuid.UUID,
    dst_id: uuid.UUID,
    edge_type: EdgeType,
    body: dict[str, Any],
) -> Edge:
    src, dst = db.get(Node, src_id), db.get(Node, dst_id)
    if src is None or dst is None or src.blueprint_id != blueprint.id:
        raise NotFound("Node not found in this blueprint")
    validate_edge(src, dst, edge_type)
    exists = db.scalar(
        select(Edge.id).where(Edge.src_id == src_id, Edge.dst_id == dst_id, Edge.type == edge_type)
    )
    if exists:
        raise Conflict("This edge already exists", code="DUPLICATE_EDGE")
    edge = Edge(blueprint_id=blueprint.id, src_id=src_id, dst_id=dst_id, type=edge_type, body=body)
    db.add(edge)
    db.commit()
    return edge


@dataclass
class NodeSpec:
    """A node in a bulk write. `ref` is a caller-chosen handle (e.g. "REQ-001")
    used by EdgeSpec before database ids exist."""

    ref: str
    type: NodeType
    title: str
    body: dict[str, Any]
    status: NodeStatus = NodeStatus.todo


@dataclass
class EdgeSpec:
    src: str
    dst: str
    type: EdgeType
    body: dict[str, Any] | None = None


def replace_graph(
    db: Session, blueprint: Blueprint, nodes: list[NodeSpec], edges: list[EdgeSpec]
) -> dict[str, uuid.UUID]:
    """Atomically replace a blueprint's whole graph (used by generation).

    Validates everything before writing; on any error nothing is changed.
    Returns ref -> node id.
    """
    refs = [n.ref for n in nodes]
    if len(set(refs)) != len(refs):
        raise AppError("Duplicate node refs in graph payload", code="INVALID_GRAPH")
    by_ref = {n.ref: n for n in nodes}
    for e in edges:
        if e.src not in by_ref or e.dst not in by_ref:
            raise AppError(f"Edge references unknown node {e.src}->{e.dst}", code="INVALID_GRAPH")
        if (by_ref[e.src].type, by_ref[e.dst].type) not in EDGE_RULES[e.type] or e.src == e.dst:
            raise AppError(f"Invalid edge {e.src} -{e.type.value}-> {e.dst}", code="INVALID_GRAPH")

    # Keys are assigned per type in payload order (REQ-001, REQ-002, ...).
    counters: dict[NodeType, int] = defaultdict(int)
    ids: dict[str, uuid.UUID] = {}
    try:
        db.execute(delete(Edge).where(Edge.blueprint_id == blueprint.id))
        db.execute(delete(Node).where(Node.blueprint_id == blueprint.id))
        for pos, spec in enumerate(nodes, start=1):
            counters[spec.type] += 1
            node = Node(
                id=uuid.uuid4(),
                blueprint_id=blueprint.id,
                type=spec.type,
                key=f"{NODE_KEY_PREFIX[spec.type]}-{counters[spec.type]:03d}",
                title=spec.title[:300],
                body=spec.body,
                status=spec.status,
                position=pos,
            )
            db.add(node)
            ids[spec.ref] = node.id
        db.flush()
        seen: set[tuple[uuid.UUID, uuid.UUID, EdgeType]] = set()
        for e in edges:
            triple = (ids[e.src], ids[e.dst], e.type)
            if triple in seen:
                continue
            seen.add(triple)
            db.add(
                Edge(
                    blueprint_id=blueprint.id,
                    src_id=triple[0],
                    dst_id=triple[1],
                    type=e.type,
                    body=e.body or {},
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ids


def get_graph(
    db: Session,
    blueprint_id: uuid.UUID,
    *,
    types: list[NodeType] | None = None,
    status: NodeStatus | None = None,
    stale: bool | None = None,
) -> tuple[list[Node], list[Edge]]:
    q = select(Node).where(Node.blueprint_id == blueprint_id)
    if types:
        q = q.where(Node.type.in_(types))
    if status:
        q = q.where(Node.status == status)
    if stale is not None:
        q = q.where(Node.stale.is_(stale))
    nodes = list(db.scalars(q.order_by(Node.position)))
    ids = {n.id for n in nodes}
    edges = [
        e
        for e in db.scalars(select(Edge).where(Edge.blueprint_id == blueprint_id))
        if e.src_id in ids and e.dst_id in ids
    ]
    return nodes, edges

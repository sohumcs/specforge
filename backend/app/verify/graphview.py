"""An in-memory, read-only snapshot of a blueprint graph.

Rules run on this snapshot, not on the ORM, so the rule engine is pure Python:
no database, no I/O, trivially unit-testable, and deterministic.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.models.enums import EdgeType, NodeType


@dataclass(frozen=True)
class GNode:
    id: uuid.UUID
    type: NodeType
    key: str
    title: str
    body: dict[str, Any]
    position: int = 0

    def text(self) -> str:
        """The natural-language content used for embeddings and NLI."""
        extra = (
            self.body.get("description")
            or self.body.get("responsibility")
            or self.body.get("summary")
            or ""
        )
        return f"{self.title}. {extra}".strip() if extra else self.title


@dataclass(frozen=True)
class GEdge:
    src: uuid.UUID
    dst: uuid.UUID
    type: EdgeType


@dataclass
class GraphView:
    nodes: dict[uuid.UUID, GNode]
    edges: list[GEdge]
    _out: dict[uuid.UUID, list[GEdge]] = field(default_factory=lambda: defaultdict(list))
    _in: dict[uuid.UUID, list[GEdge]] = field(default_factory=lambda: defaultdict(list))

    def __post_init__(self) -> None:
        for e in self.edges:
            self._out[e.src].append(e)
            self._in[e.dst].append(e)

    @classmethod
    def build(cls, nodes: list[GNode], edges: list[GEdge]) -> "GraphView":
        return cls(nodes={n.id: n for n in nodes}, edges=edges)

    def of_type(self, t: NodeType) -> list[GNode]:
        return sorted((n for n in self.nodes.values() if n.type == t), key=lambda n: n.position)

    def out(self, node_id: uuid.UUID, t: EdgeType | None = None) -> list[GEdge]:
        return [e for e in self._out[node_id] if t is None or e.type == t]

    def inc(self, node_id: uuid.UUID, t: EdgeType | None = None) -> list[GEdge]:
        return [e for e in self._in[node_id] if t is None or e.type == t]

    def degree(self, node_id: uuid.UUID) -> int:
        return len(self._out[node_id]) + len(self._in[node_id])

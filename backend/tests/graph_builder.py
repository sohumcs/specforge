"""Tiny DSL for building GraphView fixtures in rule tests."""

import uuid
from typing import Any

from app.models.enums import NODE_KEY_PREFIX, EdgeType, NodeType
from app.verify.graphview import GEdge, GNode, GraphView


class G:
    def __init__(self) -> None:
        self.nodes: dict[str, GNode] = {}
        self.edges: list[GEdge] = []
        self._count: dict[NodeType, int] = {}

    def add(
        self, ref: str, t: NodeType, title: str = "", key: str | None = None, **body: Any
    ) -> "G":
        self._count[t] = self._count.get(t, 0) + 1
        self.nodes[ref] = GNode(
            uuid.uuid4(),
            t,
            key or f"{NODE_KEY_PREFIX[t]}-{self._count[t]:03d}",
            title or ref,
            body,
            len(self.nodes),
        )
        return self

    def link(self, src: str, dst: str, t: EdgeType) -> "G":
        self.edges.append(GEdge(self.nodes[src].id, self.nodes[dst].id, t))
        return self

    def view(self) -> GraphView:
        return GraphView.build(list(self.nodes.values()), self.edges)

    def id(self, ref: str) -> uuid.UUID:
        return self.nodes[ref].id


AC = ["Given a user, when they act, then it works"]


def healthy() -> G:
    """A minimal graph that passes every rule."""
    T, E = NodeType, EdgeType
    g = G()
    g.add("R1", T.requirement, "Customers place orders", kind="functional", nfr_category="none")
    for cat in ("performance", "security", "availability"):
        g.add(f"N{cat}", T.requirement, f"{cat} target", kind="non_functional", nfr_category=cat)
    g.add("S1", T.story, "As a customer I order", acceptance_criteria=AC)
    g.add("M1", T.module, "Ordering")
    g.add(
        "E1",
        T.entity,
        "Order",
        fields=[{"name": "id", "type": "uuid", "primary_key": True, "nullable": False}],
    )
    for i, (m, p) in enumerate(
        [
            ("POST", "/orders"),
            ("GET", "/orders/{id}"),
            ("PATCH", "/orders/{id}"),
            ("DELETE", "/orders/{id}"),
        ]
    ):
        g.add(f"A{i}", T.api, f"{m} {p}", method=m, path=p)
        g.link("M1", f"A{i}", E.exposes).link(f"A{i}", "E1", E.persists)
    g.add("T1", T.test, "Order flow")
    g.add(
        "K1",
        T.risk,
        "Payment outage",
        likelihood="high",
        impact="high",
        mitigation="Retry with backoff and queue payments for later capture",
    )
    g.link("R1", "S1", E.refines).link("S1", "M1", E.implemented_by).link("S1", "T1", E.verified_by)
    for cat in ("performance", "security", "availability"):
        g.add(f"S{cat}", T.story, f"{cat} story", acceptance_criteria=AC)
        g.link(f"N{cat}", f"S{cat}", E.refines).link(f"S{cat}", "T1", E.verified_by)
        g.link(f"S{cat}", "M1", E.implemented_by)
    g.link("K1", "R1", E.threatens)
    return g

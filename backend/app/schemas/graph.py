import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import EdgeType, NodeStatus, NodeType
from app.schemas.common import ORMModel


class NodeIn(BaseModel):
    type: NodeType
    title: str = Field(min_length=1, max_length=300)
    body: dict[str, Any] = Field(default_factory=dict)
    key: str | None = Field(default=None, pattern=r"^[A-Z]{2,4}-\d{3,5}$")


class NodePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    body: dict[str, Any] | None = None


class StatusIn(BaseModel):
    status: NodeStatus


class NodeOut(ORMModel):
    id: uuid.UUID
    blueprint_id: uuid.UUID
    type: NodeType
    key: str
    title: str
    body: dict[str, Any]
    status: NodeStatus
    stale: bool


class EdgeIn(BaseModel):
    src_id: uuid.UUID
    dst_id: uuid.UUID
    type: EdgeType
    body: dict[str, Any] = Field(default_factory=dict)


class EdgeOut(ORMModel):
    id: uuid.UUID
    src_id: uuid.UUID
    dst_id: uuid.UUID
    type: EdgeType
    body: dict[str, Any]


class GraphOut(BaseModel):
    nodes: list[NodeOut]
    edges: list[EdgeOut]


class ImpactedNode(BaseModel):
    id: uuid.UUID
    key: str
    type: NodeType
    title: str
    depth: int


class ImpactOut(BaseModel):
    root_id: uuid.UUID
    impacted: list[ImpactedNode]
    by_depth: dict[int, list[uuid.UUID]]


class NodeUpdateOut(BaseModel):
    node: NodeOut
    impact: ImpactOut


class TraceOut(BaseModel):
    root_id: uuid.UUID
    upstream: list[ImpactedNode]
    downstream: list[ImpactedNode]

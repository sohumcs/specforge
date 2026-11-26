import uuid

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser
from app.models import Blueprint, Edge, Node
from app.models.enums import NodeStatus, NodeType, Role
from app.schemas.common import Page
from app.schemas.graph import (
    EdgeIn,
    EdgeOut,
    GraphOut,
    ImpactOut,
    NodeIn,
    NodeOut,
    NodePatch,
    NodeUpdateOut,
    StatusIn,
    TraceOut,
)
from app.schemas.projects import BlueprintIn, BlueprintOut, BlueprintPatch
from app.services import graph
from app.services.access import (
    authorize_blueprint,
    authorize_edge,
    authorize_node,
    authorize_project,
)

router = APIRouter(tags=["blueprints"])


# ------------------------------------------------------------------ blueprints


@router.get("/projects/{project_id}/blueprints", response_model=Page[BlueprintOut])
def list_blueprints(
    project_id: uuid.UUID,
    db: DB,
    user: CurrentUser,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> Page[BlueprintOut]:
    authorize_project(db, user, project_id, Role.viewer)
    base = select(Blueprint).where(Blueprint.project_id == project_id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    items = db.scalars(base.order_by(Blueprint.created_at.desc()).limit(limit).offset(offset))
    return Page(
        items=[BlueprintOut.model_validate(b) for b in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/projects/{project_id}/blueprints",
    response_model=BlueprintOut,
    status_code=status.HTTP_201_CREATED,
)
def create_blueprint(
    project_id: uuid.UUID, body: BlueprintIn, db: DB, user: CurrentUser
) -> BlueprintOut:
    authorize_project(db, user, project_id, Role.editor)
    bp = Blueprint(
        project_id=project_id, title=body.title, brief=body.brief, settings=body.settings
    )
    db.add(bp)
    db.commit()
    return BlueprintOut.model_validate(bp)


@router.get("/blueprints/{blueprint_id}", response_model=BlueprintOut)
def get_blueprint(blueprint_id: uuid.UUID, db: DB, user: CurrentUser) -> BlueprintOut:
    return BlueprintOut.model_validate(authorize_blueprint(db, user, blueprint_id, Role.viewer))


@router.patch("/blueprints/{blueprint_id}", response_model=BlueprintOut)
def update_blueprint(
    blueprint_id: uuid.UUID, body: BlueprintPatch, db: DB, user: CurrentUser
) -> BlueprintOut:
    bp = authorize_blueprint(db, user, blueprint_id, Role.editor)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(bp, field, value)
    db.commit()
    return BlueprintOut.model_validate(bp)


@router.delete("/blueprints/{blueprint_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_blueprint(blueprint_id: uuid.UUID, db: DB, user: CurrentUser) -> None:
    bp = authorize_blueprint(db, user, blueprint_id, Role.owner)
    db.delete(bp)
    db.commit()


@router.get("/blueprints/{blueprint_id}/graph", response_model=GraphOut)
def get_graph(
    blueprint_id: uuid.UUID,
    db: DB,
    user: CurrentUser,
    types: list[NodeType] | None = Query(None, description="Only these node types"),
    status_filter: NodeStatus | None = Query(None, alias="status"),
    stale: bool | None = Query(None),
) -> GraphOut:
    authorize_blueprint(db, user, blueprint_id, Role.viewer)
    nodes, edges = graph.get_graph(db, blueprint_id, types=types, status=status_filter, stale=stale)
    return GraphOut(
        nodes=[NodeOut.model_validate(n) for n in nodes],
        edges=[EdgeOut.model_validate(e) for e in edges],
    )


# ------------------------------------------------------------------ nodes


@router.get("/blueprints/{blueprint_id}/nodes", response_model=Page[NodeOut])
def list_nodes(
    blueprint_id: uuid.UUID,
    db: DB,
    user: CurrentUser,
    type_filter: NodeType | None = Query(None, alias="type"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page[NodeOut]:
    authorize_blueprint(db, user, blueprint_id, Role.viewer)
    base = select(Node).where(Node.blueprint_id == blueprint_id)
    if type_filter:
        base = base.where(Node.type == type_filter)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    items = db.scalars(base.order_by(Node.position).limit(limit).offset(offset))
    return Page(
        items=[NodeOut.model_validate(n) for n in items], total=total, limit=limit, offset=offset
    )


@router.post(
    "/blueprints/{blueprint_id}/nodes", response_model=NodeOut, status_code=status.HTTP_201_CREATED
)
def create_node(blueprint_id: uuid.UUID, body: NodeIn, db: DB, user: CurrentUser) -> NodeOut:
    bp = authorize_blueprint(db, user, blueprint_id, Role.editor)
    node = graph.create_node(
        db, bp, node_type=body.type, title=body.title, body=body.body, key=body.key
    )
    return NodeOut.model_validate(node)


@router.get("/nodes/{node_id}", response_model=NodeOut)
def get_node(node_id: uuid.UUID, db: DB, user: CurrentUser) -> NodeOut:
    return NodeOut.model_validate(authorize_node(db, user, node_id, Role.viewer))


@router.patch("/nodes/{node_id}", response_model=NodeUpdateOut)
def update_node(node_id: uuid.UUID, body: NodePatch, db: DB, user: CurrentUser) -> NodeUpdateOut:
    """Edit content. Everything downstream is marked stale in the same
    transaction, and the impact set is returned grouped by hop distance."""
    node = authorize_node(db, user, node_id, Role.editor)
    reached = graph.update_node(db, node, user_id=user.id, title=body.title, body=body.body)
    return NodeUpdateOut(
        node=NodeOut.model_validate(node),
        impact=ImpactOut.model_validate(graph.impact_payload(db, node, reached)),
    )


@router.patch("/nodes/{node_id}/status", response_model=NodeOut)
def set_status(node_id: uuid.UUID, body: StatusIn, db: DB, user: CurrentUser) -> NodeOut:
    node = authorize_node(db, user, node_id, Role.editor)
    return NodeOut.model_validate(graph.set_status(db, node, body.status))


@router.delete("/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_node(node_id: uuid.UUID, db: DB, user: CurrentUser) -> None:
    graph.delete_node(db, authorize_node(db, user, node_id, Role.editor))


@router.get("/nodes/{node_id}/impact", response_model=ImpactOut)
def node_impact(node_id: uuid.UUID, db: DB, user: CurrentUser) -> ImpactOut:
    """Dry run: what WOULD be affected if this node changed (nothing is marked)."""
    node = authorize_node(db, user, node_id, Role.viewer)
    return ImpactOut.model_validate(
        graph.impact_payload(db, node, graph.downstream_impact(db, node))
    )


@router.get("/nodes/{node_id}/trace", response_model=TraceOut)
def node_trace(node_id: uuid.UUID, db: DB, user: CurrentUser) -> TraceOut:
    node = authorize_node(db, user, node_id, Role.viewer)
    return TraceOut.model_validate(
        {
            "root_id": node.id,
            "upstream": graph.describe(db, graph.upstream_trace(db, node)),
            "downstream": graph.describe(db, graph.downstream_impact(db, node)),
        }
    )


# ------------------------------------------------------------------ edges


@router.post(
    "/blueprints/{blueprint_id}/edges", response_model=EdgeOut, status_code=status.HTTP_201_CREATED
)
def create_edge(blueprint_id: uuid.UUID, body: EdgeIn, db: DB, user: CurrentUser) -> EdgeOut:
    bp = authorize_blueprint(db, user, blueprint_id, Role.editor)
    edge = graph.create_edge(
        db, bp, src_id=body.src_id, dst_id=body.dst_id, edge_type=body.type, body=body.body
    )
    return EdgeOut.model_validate(edge)


@router.delete("/edges/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_edge(edge_id: uuid.UUID, db: DB, user: CurrentUser) -> None:
    edge: Edge = authorize_edge(db, user, edge_id, Role.editor)
    db.delete(edge)
    db.commit()

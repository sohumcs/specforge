"""Server-side RBAC.

Roles are per project: viewer < editor < owner. Admins bypass project checks.
A user who is not a member gets 404, not 403, so project ids can't be probed;
a member with too low a role gets 403.
"""

import uuid

from sqlalchemy.orm import Session

from app.core.errors import Forbidden, NotFound
from app.models import Blueprint, Edge, Node, Project, ProjectMember, User
from app.models.enums import ROLE_RANK, Role


def role_in_project(db: Session, user: User, project_id: uuid.UUID) -> Role | None:
    member = db.get(ProjectMember, (project_id, user.id))
    return member.role if member else None


def authorize_project(db: Session, user: User, project_id: uuid.UUID, min_role: Role) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise NotFound("Project not found")
    if user.is_admin:
        return project
    role = role_in_project(db, user, project_id)
    if role is None:
        raise NotFound("Project not found")
    if ROLE_RANK[role] < ROLE_RANK[min_role]:
        raise Forbidden(
            f"This action needs the '{min_role.value}' role",
            details={"required": min_role.value, "current": role.value},
        )
    return project


def authorize_blueprint(
    db: Session, user: User, blueprint_id: uuid.UUID, min_role: Role
) -> Blueprint:
    bp = db.get(Blueprint, blueprint_id)
    if bp is None:
        raise NotFound("Blueprint not found")
    authorize_project(db, user, bp.project_id, min_role)
    return bp


def authorize_node(db: Session, user: User, node_id: uuid.UUID, min_role: Role) -> Node:
    node = db.get(Node, node_id)
    if node is None:
        raise NotFound("Node not found")
    authorize_blueprint(db, user, node.blueprint_id, min_role)
    return node


def authorize_edge(db: Session, user: User, edge_id: uuid.UUID, min_role: Role) -> Edge:
    edge = db.get(Edge, edge_id)
    if edge is None:
        raise NotFound("Edge not found")
    authorize_blueprint(db, user, edge.blueprint_id, min_role)
    return edge

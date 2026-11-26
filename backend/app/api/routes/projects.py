import uuid

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select

from app.api.deps import DB, AdminUser, CurrentUser
from app.core.errors import AppError, Conflict, NotFound
from app.models import Project, ProjectMember, User
from app.models.enums import Role
from app.schemas.auth import UserOut
from app.schemas.common import Page
from app.schemas.projects import (
    MemberIn,
    MemberOut,
    MemberRoleIn,
    ProjectIn,
    ProjectOut,
    ProjectPatch,
)
from app.services.access import authorize_project, role_in_project

router = APIRouter(prefix="/projects", tags=["projects"])


def _out(project: Project, role: Role | None) -> ProjectOut:
    out = ProjectOut.model_validate(project)
    out.my_role = role
    return out


@router.get("", response_model=Page[ProjectOut])
def list_projects(
    db: DB,
    user: CurrentUser,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    q: str | None = Query(None, max_length=100, description="Filter by name (case-insensitive)"),
) -> Page[ProjectOut]:
    base = select(Project, ProjectMember.role).outerjoin(
        ProjectMember, (ProjectMember.project_id == Project.id) & (ProjectMember.user_id == user.id)
    )
    if not user.is_admin:
        base = base.where(ProjectMember.user_id == user.id)
    if q:
        base = base.where(Project.name.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(base.order_by(Project.created_at.desc()).limit(limit).offset(offset)).all()
    return Page(items=[_out(p, r) for p, r in rows], total=total, limit=limit, offset=offset)


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(body: ProjectIn, db: DB, user: CurrentUser) -> ProjectOut:
    if user.is_demo:
        raise AppError(
            "The demo account works inside the Sandbox project",
            code="DEMO_READ_ONLY",
            status_code=403,
        )
    project = Project(name=body.name, description=body.description)
    db.add(project)
    db.flush()
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role=Role.owner))
    db.commit()
    return _out(project, Role.owner)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: uuid.UUID, db: DB, user: CurrentUser) -> ProjectOut:
    project = authorize_project(db, user, project_id, Role.viewer)
    return _out(project, role_in_project(db, user, project_id))


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: uuid.UUID, body: ProjectPatch, db: DB, user: CurrentUser
) -> ProjectOut:
    project = authorize_project(db, user, project_id, Role.owner)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(project, field, value)
    db.commit()
    return _out(project, role_in_project(db, user, project_id))


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: uuid.UUID, db: DB, user: CurrentUser) -> None:
    project = authorize_project(db, user, project_id, Role.owner)
    if project.is_sandbox:
        raise AppError(
            "The sandbox project can't be deleted", code="SANDBOX_PROTECTED", status_code=403
        )
    db.delete(project)
    db.commit()


# ------------------------------------------------------------------ members


def _member_out(m: ProjectMember) -> MemberOut:
    return MemberOut(
        user_id=m.user_id, email=m.user.email, display_name=m.user.display_name, role=m.role
    )


@router.get("/{project_id}/members", response_model=list[MemberOut])
def list_members(project_id: uuid.UUID, db: DB, user: CurrentUser) -> list[MemberOut]:
    authorize_project(db, user, project_id, Role.viewer)
    members = db.scalars(select(ProjectMember).where(ProjectMember.project_id == project_id))
    return [_member_out(m) for m in members]


@router.post("/{project_id}/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
def add_member(project_id: uuid.UUID, body: MemberIn, db: DB, user: CurrentUser) -> MemberOut:
    authorize_project(db, user, project_id, Role.owner)
    target = db.scalar(select(User).where(User.email == body.email))
    if target is None:
        raise NotFound("No user with that email")
    if db.get(ProjectMember, (project_id, target.id)):
        raise Conflict("User is already a member", code="ALREADY_MEMBER")
    member = ProjectMember(project_id=project_id, user_id=target.id, role=body.role)
    db.add(member)
    db.commit()
    return _member_out(member)


def _ensure_not_last_owner(db: DB, project_id: uuid.UUID, member: ProjectMember) -> None:
    if member.role != Role.owner:
        return
    owners = db.scalar(
        select(func.count()).where(
            ProjectMember.project_id == project_id, ProjectMember.role == Role.owner
        )
    )
    if (owners or 0) <= 1:
        raise AppError("A project must keep at least one owner", code="LAST_OWNER")


@router.patch("/{project_id}/members/{user_id}", response_model=MemberOut)
def change_role(
    project_id: uuid.UUID, user_id: uuid.UUID, body: MemberRoleIn, db: DB, user: CurrentUser
) -> MemberOut:
    authorize_project(db, user, project_id, Role.owner)
    member = db.get(ProjectMember, (project_id, user_id))
    if member is None:
        raise NotFound("Member not found")
    if body.role != Role.owner:
        _ensure_not_last_owner(db, project_id, member)
    member.role = body.role
    db.commit()
    return _member_out(member)


@router.delete("/{project_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(project_id: uuid.UUID, user_id: uuid.UUID, db: DB, user: CurrentUser) -> None:
    authorize_project(db, user, project_id, Role.owner)
    member = db.get(ProjectMember, (project_id, user_id))
    if member is None:
        raise NotFound("Member not found")
    _ensure_not_last_owner(db, project_id, member)
    db.delete(member)
    db.commit()


admin_router = APIRouter(prefix="/admin", tags=["admin"])


@admin_router.get("/users", response_model=Page[UserOut])
def list_users(
    db: DB, _: AdminUser, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)
) -> Page[UserOut]:
    total = db.scalar(select(func.count()).select_from(User)) or 0
    users = db.scalars(select(User).order_by(User.created_at).limit(limit).offset(offset))
    return Page(
        items=[UserOut.model_validate(u) for u in users], total=total, limit=limit, offset=offset
    )

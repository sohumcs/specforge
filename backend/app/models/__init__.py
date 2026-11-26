"""ORM models. Importing this package registers every table on Base.metadata."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import (
    BlueprintStatus,
    EdgeType,
    IssueCategory,
    JobKind,
    JobStatus,
    NodeStatus,
    NodeType,
    Role,
    Severity,
)

EMBEDDING_DIM = 384  # all-MiniLM-L6-v2


def pg_enum(enum_cls: type[StrEnum], name: str) -> SAEnum:
    return SAEnum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_sandbox: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    members: Mapped[list["ProjectMember"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProjectMember(Base):
    __tablename__ = "project_members"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[Role] = mapped_column(pg_enum(Role, "project_role"), nullable=False)

    project: Mapped[Project] = relationship(back_populates="members")
    user: Mapped[User] = relationship()


class Blueprint(TimestampMixin, Base):
    __tablename__ = "blueprints"

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    brief: Mapped[str] = mapped_column(Text, nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[BlueprintStatus] = mapped_column(
        pg_enum(BlueprintStatus, "blueprint_status"), default=BlueprintStatus.draft, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    quality_score: Mapped[int | None] = mapped_column(Integer)
    provider: Mapped[str | None] = mapped_column(String(40))
    cache_key: Mapped[str | None] = mapped_column(String(64))
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Node(TimestampMixin, Base):
    __tablename__ = "nodes"
    __table_args__ = (
        UniqueConstraint("blueprint_id", "key", name="uq_nodes_blueprint_key"),
        Index("ix_nodes_blueprint_type", "blueprint_id", "type"),
        Index(
            "ix_nodes_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    blueprint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("blueprints.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[NodeType] = mapped_column(pg_enum(NodeType, "node_type"), nullable=False)
    key: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[NodeStatus] = mapped_column(
        pg_enum(NodeStatus, "node_status"), default=NodeStatus.todo, nullable=False
    )
    stale: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))


class Edge(Base):
    __tablename__ = "edges"
    __table_args__ = (
        UniqueConstraint("src_id", "dst_id", "type", name="uq_edges_src_dst_type"),
        CheckConstraint("src_id <> dst_id", name="no_self_loop"),
        Index("ix_edges_blueprint_src", "blueprint_id", "src_id"),
        Index("ix_edges_blueprint_dst", "blueprint_id", "dst_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    blueprint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("blueprints.id", ondelete="CASCADE"), nullable=False
    )
    src_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False
    )
    dst_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[EdgeType] = mapped_column(pg_enum(EdgeType, "edge_type"), nullable=False)
    body: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_blueprint_status", "blueprint_id", "status"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    blueprint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("blueprints.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[JobKind] = mapped_column(pg_enum(JobKind, "job_kind"), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        pg_enum(JobStatus, "job_status"), default=JobStatus.queued, nullable=False
    )
    step: Mapped[str] = mapped_column(String(40), default="queued", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), unique=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class QualityReport(Base):
    __tablename__ = "quality_reports"

    id: Mapped[uuid.UUID] = uuid_pk()
    blueprint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("blueprints.id", ondelete="CASCADE"), index=True, nullable=False
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    issues: Mapped[list["Issue"]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )


class Issue(Base):
    __tablename__ = "issues"

    id: Mapped[uuid.UUID] = uuid_pk()
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("quality_reports.id", ondelete="CASCADE"), index=True, nullable=False
    )
    rule_code: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[IssueCategory] = mapped_column(
        pg_enum(IssueCategory, "issue_category"), nullable=False
    )
    severity: Mapped[Severity] = mapped_column(pg_enum(Severity, "severity"), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    node_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), default=list, nullable=False
    )
    fix_hint: Mapped[str] = mapped_column(Text, default="", nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    report: Mapped[QualityReport] = relationship(back_populates="issues")


class GenerationCache(Base):
    __tablename__ = "generation_cache"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Hash of the normalised brief alone: lets an older-prompt result serve as a
    # fallback when every LLM is down ("stale cache" link of the chain).
    brief_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ChangeEvent(Base):
    __tablename__ = "change_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    blueprint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("blueprints.id", ondelete="CASCADE"), index=True, nullable=False
    )
    node_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("nodes.id", ondelete="SET NULL"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    before: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    after: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    impacted: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), default=list, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = [
    "EMBEDDING_DIM",
    "Blueprint",
    "ChangeEvent",
    "Edge",
    "GenerationCache",
    "Issue",
    "Job",
    "Node",
    "Project",
    "ProjectMember",
    "QualityReport",
    "RefreshToken",
    "User",
]

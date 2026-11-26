"""initial schema

Revision ID: 17e2d1b44e2e
Revises:
Create Date: 2026-11-26 11:24:19.082652
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "17e2d1b44e2e"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.create_table(
        "generation_cache",
        sa.Column("cache_key", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("cache_key", name=op.f("pk_generation_cache")),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("is_sandbox", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "blueprints",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("brief", sa.Text(), nullable=False),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.Enum("draft", "generating", "ready", "failed", name="blueprint_status"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("quality_score", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=True),
        sa.Column("cache_key", sa.String(length=64), nullable=True),
        sa.Column("is_sample", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_blueprints_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_blueprints")),
    )
    op.create_index(op.f("ix_blueprints_project_id"), "blueprints", ["project_id"], unique=False)
    op.create_table(
        "project_members",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "role", sa.Enum("viewer", "editor", "owner", name="project_role"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_project_members_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_project_members_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("project_id", "user_id", name=op.f("pk_project_members")),
    )
    op.create_index(
        op.f("ix_project_members_user_id"), "project_members", ["user_id"], unique=False
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("family_id", sa.UUID(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index(
        op.f("ix_refresh_tokens_family_id"), "refresh_tokens", ["family_id"], unique=False
    )
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)
    op.create_table(
        "jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("blueprint_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum("generate", "verify", "regenerate_subgraph", "fix_issue", name="job_kind"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("queued", "running", "succeeded", "failed", "dead", name="job_status"),
            nullable=False,
        ),
        sa.Column("step", sa.String(length=40), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["blueprint_id"],
            ["blueprints.id"],
            name=op.f("fk_jobs_blueprint_id_blueprints"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_jobs_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_jobs_idempotency_key")),
    )
    op.create_index(op.f("ix_jobs_blueprint_id"), "jobs", ["blueprint_id"], unique=False)
    op.create_table(
        "nodes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("blueprint_id", sa.UUID(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "requirement", "story", "module", "api", "entity", "test", "risk", name="node_type"
            ),
            nullable=False,
        ),
        sa.Column("key", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.Enum("todo", "in_progress", "in_review", "done", name="node_status"),
            nullable=False,
        ),
        sa.Column("stale", sa.Boolean(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["blueprint_id"],
            ["blueprints.id"],
            name=op.f("fk_nodes_blueprint_id_blueprints"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_nodes")),
        sa.UniqueConstraint("blueprint_id", "key", name="uq_nodes_blueprint_key"),
    )
    op.create_index("ix_nodes_blueprint_type", "nodes", ["blueprint_id", "type"], unique=False)
    op.create_index(
        "ix_nodes_embedding_hnsw",
        "nodes",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_table(
        "quality_reports",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("blueprint_id", sa.UUID(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("breakdown", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["blueprint_id"],
            ["blueprints.id"],
            name=op.f("fk_quality_reports_blueprint_id_blueprints"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quality_reports")),
    )
    op.create_index(
        op.f("ix_quality_reports_blueprint_id"), "quality_reports", ["blueprint_id"], unique=False
    )
    op.create_table(
        "change_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("blueprint_id", sa.UUID(), nullable=False),
        sa.Column("node_id", sa.UUID(), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("impacted", postgresql.ARRAY(sa.UUID()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["blueprint_id"],
            ["blueprints.id"],
            name=op.f("fk_change_events_blueprint_id_blueprints"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["nodes.id"],
            name=op.f("fk_change_events_node_id_nodes"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_change_events_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_change_events")),
    )
    op.create_index(
        op.f("ix_change_events_blueprint_id"), "change_events", ["blueprint_id"], unique=False
    )
    op.create_index(op.f("ix_change_events_node_id"), "change_events", ["node_id"], unique=False)
    op.create_table(
        "edges",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("blueprint_id", sa.UUID(), nullable=False),
        sa.Column("src_id", sa.UUID(), nullable=False),
        sa.Column("dst_id", sa.UUID(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "refines",
                "implemented_by",
                "exposes",
                "persists",
                "relates_to",
                "verified_by",
                "threatens",
                "depends_on",
                name="edge_type",
            ),
            nullable=False,
        ),
        sa.Column("body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("src_id <> dst_id", name=op.f("ck_edges_no_self_loop")),
        sa.ForeignKeyConstraint(
            ["blueprint_id"],
            ["blueprints.id"],
            name=op.f("fk_edges_blueprint_id_blueprints"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dst_id"], ["nodes.id"], name=op.f("fk_edges_dst_id_nodes"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["src_id"], ["nodes.id"], name=op.f("fk_edges_src_id_nodes"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_edges")),
        sa.UniqueConstraint("src_id", "dst_id", "type", name="uq_edges_src_dst_type"),
    )
    op.create_index("ix_edges_blueprint_dst", "edges", ["blueprint_id", "dst_id"], unique=False)
    op.create_index("ix_edges_blueprint_src", "edges", ["blueprint_id", "src_id"], unique=False)
    op.create_table(
        "issues",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("report_id", sa.UUID(), nullable=False),
        sa.Column("rule_code", sa.String(length=20), nullable=False),
        sa.Column(
            "category",
            sa.Enum(
                "traceability",
                "completeness",
                "consistency",
                "uniqueness",
                "conventions",
                name="issue_category",
            ),
            nullable=False,
        ),
        sa.Column("severity", sa.Enum("low", "medium", "high", name="severity"), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("node_ids", postgresql.ARRAY(sa.UUID()), nullable=False),
        sa.Column("fix_hint", sa.Text(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["quality_reports.id"],
            name=op.f("fk_issues_report_id_quality_reports"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_issues")),
    )
    op.create_index(op.f("ix_issues_report_id"), "issues", ["report_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_issues_report_id"), table_name="issues")
    op.drop_table("issues")
    op.drop_index("ix_edges_blueprint_src", table_name="edges")
    op.drop_index("ix_edges_blueprint_dst", table_name="edges")
    op.drop_table("edges")
    op.drop_index(op.f("ix_change_events_node_id"), table_name="change_events")
    op.drop_index(op.f("ix_change_events_blueprint_id"), table_name="change_events")
    op.drop_table("change_events")
    op.drop_index(op.f("ix_quality_reports_blueprint_id"), table_name="quality_reports")
    op.drop_table("quality_reports")
    op.drop_index(
        "ix_nodes_embedding_hnsw",
        table_name="nodes",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_index("ix_nodes_blueprint_type", table_name="nodes")
    op.drop_table("nodes")
    op.drop_index(op.f("ix_jobs_blueprint_id"), table_name="jobs")
    op.drop_table("jobs")
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_family_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index(op.f("ix_project_members_user_id"), table_name="project_members")
    op.drop_table("project_members")
    op.drop_index(op.f("ix_blueprints_project_id"), table_name="blueprints")
    op.drop_table("blueprints")
    op.drop_table("users")
    op.drop_table("projects")
    op.drop_table("generation_cache")
    op.execute("DROP TYPE IF EXISTS blueprint_status")
    op.execute("DROP TYPE IF EXISTS project_role")
    op.execute("DROP TYPE IF EXISTS job_kind")
    op.execute("DROP TYPE IF EXISTS job_status")
    op.execute("DROP TYPE IF EXISTS node_type")
    op.execute("DROP TYPE IF EXISTS node_status")
    op.execute("DROP TYPE IF EXISTS edge_type")
    op.execute("DROP TYPE IF EXISTS issue_category")
    op.execute("DROP TYPE IF EXISTS severity")

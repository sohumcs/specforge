"""quality_reports.created_at uses clock_timestamp() and is indexed

Revision ID: 0003_report_clock
Revises: 97c2760713f7
Create Date: 2026-11-26
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_report_clock"
down_revision: str | None = "97c2760713f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("quality_reports", "created_at", server_default=sa.text("clock_timestamp()"))
    op.create_index(op.f("ix_quality_reports_created_at"), "quality_reports", ["created_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_quality_reports_created_at"), table_name="quality_reports")
    op.alter_column("quality_reports", "created_at", server_default=sa.text("now()"))

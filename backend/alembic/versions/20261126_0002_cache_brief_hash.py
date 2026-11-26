"""cache brief hash and job index

Revision ID: 97c2760713f7
Revises: 17e2d1b44e2e
Create Date: 2026-11-26 12:02:18.588374
"""
from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op


revision: str = '97c2760713f7'
down_revision: str | None = '17e2d1b44e2e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default so existing rows get a value; then drop it (app always sets it).
    op.add_column('generation_cache', sa.Column('brief_hash', sa.String(length=64), nullable=False, server_default=''))
    op.alter_column('generation_cache', 'brief_hash', server_default=None)
    op.create_index(op.f('ix_generation_cache_brief_hash'), 'generation_cache', ['brief_hash'], unique=False)
    op.create_index('ix_jobs_blueprint_status', 'jobs', ['blueprint_id', 'status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_jobs_blueprint_status', table_name='jobs')
    op.drop_index(op.f('ix_generation_cache_brief_hash'), table_name='generation_cache')
    op.drop_column('generation_cache', 'brief_hash')

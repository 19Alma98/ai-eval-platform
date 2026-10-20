"""scores and feedback per OTel trace

Revision ID: 0014_trace_scores
Revises: 0013_experiment_metrics
Create Date: 2026-10-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from opengrade_server.infrastructure.migration_helpers import (
    json_server_default,
    now_server_default,
    portable_json,
)

revision: str = "0014_trace_scores"
down_revision: str | None = "0013_experiment_metrics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("trace_scores"):
        return
    op.create_table(
        "trace_scores",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("label", sa.String(length=32), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("threshold", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("author", sa.String(length=200), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "metadata",
            portable_json(),
            nullable=False,
            server_default=json_server_default("{}"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=now_server_default(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=now_server_default(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "trace_id", "name", "source", "author", name="uq_trace_scores_key"
        ),
    )
    op.create_index("ix_trace_scores_project_updated", "trace_scores", ["project_id", "updated_at"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("trace_scores"):
        op.drop_index("ix_trace_scores_project_updated", table_name="trace_scores")
        op.drop_table("trace_scores")

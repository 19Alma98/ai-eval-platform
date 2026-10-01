"""create traces and spans tables

Revision ID: 0002_create_traces_spans
Revises: 0001_create_projects
Create Date: 2026-09-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_create_traces_spans"
down_revision: str | None = "0001_create_projects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "traces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("environment", sa.String(length=200), nullable=True),
        sa.Column("user_id", sa.String(length=200), nullable=True),
        sa.Column("session_id", sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "trace_id", name="uq_traces_project_trace_id"),
    )
    op.create_index(
        "ix_traces_project_start_time",
        "traces",
        ["project_id", "start_time"],
        unique=False,
    )
    op.create_index(
        "ix_traces_project_status",
        "traces",
        ["project_id", "status"],
        unique=False,
    )

    op.create_table(
        "spans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trace_pk", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("span_id", sa.String(length=16), nullable=False),
        sa.Column("parent_span_id", sa.String(length=16), nullable=True),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "events",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["trace_pk"], ["traces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_spans_trace_pk", "spans", ["trace_pk"], unique=False)
    op.create_index(
        "ix_spans_project_start_time",
        "spans",
        ["project_id", "start_time"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_spans_project_start_time", table_name="spans")
    op.drop_index("ix_spans_trace_pk", table_name="spans")
    op.drop_table("spans")
    op.drop_index("ix_traces_project_status", table_name="traces")
    op.drop_index("ix_traces_project_start_time", table_name="traces")
    op.drop_table("traces")

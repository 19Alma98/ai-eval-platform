"""per-project retention of production data

Revision ID: 0022_project_retention
Revises: 0021_trace_version
Create Date: 2026-10-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_project_retention"
down_revision: str | None = "0021_trace_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column() -> bool:
    return any(
        c["name"] == "retention_days" for c in sa.inspect(op.get_bind()).get_columns("projects")
    )


def upgrade() -> None:
    if not _has_column():
        with op.batch_alter_table("projects") as batch_op:
            batch_op.add_column(sa.Column("retention_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    if _has_column():
        with op.batch_alter_table("projects") as batch_op:
            batch_op.drop_column("retention_days")

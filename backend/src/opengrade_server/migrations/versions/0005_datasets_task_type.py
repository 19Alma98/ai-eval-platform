"""add datasets.task_type

Revision ID: 0005_datasets_task_type
Revises: 0004_rename_experiment_version
Create Date: 2026-10-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_datasets_task_type"
down_revision: str | None = "0004_rename_experiment_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "datasets",
        sa.Column("task_type", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_datasets_project_task_type", "datasets", ["project_id", "task_type"])


def downgrade() -> None:
    op.drop_index("ix_datasets_project_task_type", table_name="datasets")
    op.drop_column("datasets", "task_type")

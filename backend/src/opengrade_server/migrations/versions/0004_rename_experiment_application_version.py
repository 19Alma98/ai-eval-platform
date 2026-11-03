"""rename experiments.application_version to version

Revision ID: 0004_rename_experiment_version
Revises: 0003_create_evaluation_tables
Create Date: 2026-10-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_rename_experiment_version"
down_revision: str | None = "0003_create_evaluation_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("experiments")}
    if "application_version" in columns and "version" not in columns:
        op.rename_column("experiments", "application_version", "version")


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("experiments")}
    if "version" in columns and "application_version" not in columns:
        op.rename_column("experiments", "version", "application_version")

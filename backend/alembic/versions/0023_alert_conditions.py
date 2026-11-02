"""drift / anomaly conditions on alert rules

Revision ID: 0023_alert_conditions
Revises: 0022_project_retention
Create Date: 2026-11-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_alert_conditions"
down_revision: str | None = "0022_project_retention"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = ("condition", "baseline_minutes", "last_observed", "last_baseline")


def _columns() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("alert_rules")}


def upgrade() -> None:
    existing = _columns()
    with op.batch_alter_table("alert_rules") as batch_op:
        if "condition" not in existing:
            batch_op.add_column(
                sa.Column(
                    "condition", sa.String(length=16), nullable=False, server_default="threshold"
                )
            )
        if "baseline_minutes" not in existing:
            batch_op.add_column(sa.Column("baseline_minutes", sa.Integer(), nullable=True))
        if "last_observed" not in existing:
            batch_op.add_column(sa.Column("last_observed", sa.Float(), nullable=True))
        if "last_baseline" not in existing:
            batch_op.add_column(sa.Column("last_baseline", sa.Float(), nullable=True))


def downgrade() -> None:
    existing = _columns()
    with op.batch_alter_table("alert_rules") as batch_op:
        for name in reversed(_COLUMNS):
            if name in existing:
                batch_op.drop_column(name)

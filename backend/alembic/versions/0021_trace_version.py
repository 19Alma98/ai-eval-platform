"""release version on traces, environment/version filters on alert rules

Revision ID: 0021_trace_version
Revises: 0020_alerts
Create Date: 2026-10-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_trace_version"
down_revision: str | None = "0020_alerts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_traces_project_version_start_time"


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "version" not in _columns("traces"):
        with op.batch_alter_table("traces") as batch_op:
            batch_op.add_column(sa.Column("version", sa.String(length=200), nullable=True))
        op.create_index(_INDEX, "traces", ["project_id", "version", "start_time"])
    alert_columns = _columns("alert_rules")
    with op.batch_alter_table("alert_rules") as batch_op:
        if "environment" not in alert_columns:
            batch_op.add_column(sa.Column("environment", sa.String(length=200), nullable=True))
        if "version" not in alert_columns:
            batch_op.add_column(sa.Column("version", sa.String(length=200), nullable=True))


def downgrade() -> None:
    alert_columns = _columns("alert_rules")
    with op.batch_alter_table("alert_rules") as batch_op:
        if "version" in alert_columns:
            batch_op.drop_column("version")
        if "environment" in alert_columns:
            batch_op.drop_column("environment")
    if "version" in _columns("traces"):
        op.drop_index(_INDEX, table_name="traces")
        with op.batch_alter_table("traces") as batch_op:
            batch_op.drop_column("version")

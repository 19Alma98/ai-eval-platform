"""trace tags and the trace attribute search index (tags + metadata key:value)

Revision ID: 0024_trace_tags
Revises: 0023_alert_conditions
Create Date: 2026-11-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0024_trace_tags"
down_revision: str | None = "0023_alert_conditions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "trace_attributes"
_INDEX = "ix_trace_attributes_project_key_value"


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    inspector = _inspector()
    if "tags" not in {c["name"] for c in inspector.get_columns("traces")}:
        with op.batch_alter_table("traces") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "tags",
                    sa.JSON().with_variant(JSONB(), "postgresql"),
                    nullable=False,
                    server_default="[]",
                )
            )
    if _TABLE not in inspector.get_table_names():
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "trace_pk",
                sa.Uuid(),
                sa.ForeignKey("traces.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("project_id", sa.Uuid(), nullable=False),
            sa.Column("key", sa.String(length=210), nullable=False),
            sa.Column("value", sa.String(length=500), nullable=False),
            sa.UniqueConstraint(
                "trace_pk", "key", "value", name="uq_trace_attributes_trace_key_value"
            ),
        )
        op.create_index(_INDEX, _TABLE, ["project_id", "key", "value"])


def downgrade() -> None:
    inspector = _inspector()
    if _TABLE in inspector.get_table_names():
        op.drop_index(_INDEX, table_name=_TABLE)
        op.drop_table(_TABLE)
    if "tags" in {c["name"] for c in inspector.get_columns("traces")}:
        with op.batch_alter_table("traces") as batch_op:
            batch_op.drop_column("tags")

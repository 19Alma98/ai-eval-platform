"""server-side alert rules and their event log

Revision ID: 0020_alerts
Revises: 0019_item_repeats
Create Date: 2026-10-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from opengrade_server.infrastructure.migration_helpers import now_server_default

revision: str = "0020_alerts"
down_revision: str | None = "0019_item_repeats"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "alert_rules" not in existing:
        op.create_table(
            "alert_rules",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("project_id", sa.Uuid(), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("metric", sa.String(length=64), nullable=False),
            sa.Column("operator", sa.String(length=8), nullable=False),
            sa.Column("threshold", sa.Float(), nullable=False),
            sa.Column("window_minutes", sa.Integer(), nullable=False),
            sa.Column("min_samples", sa.Integer(), nullable=False),
            sa.Column("score_name", sa.String(length=200), nullable=True),
            sa.Column("score_source", sa.String(length=64), nullable=True),
            sa.Column("webhook_url", sa.String(length=2000), nullable=True),
            sa.Column(
                "webhook_format", sa.String(length=16), server_default="json", nullable=False
            ),
            sa.Column("repeat_minutes", sa.Integer(), nullable=True),
            sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
            sa.Column("state", sa.String(length=16), server_default="no_data", nullable=False),
            sa.Column("last_value", sa.Float(), nullable=True),
            sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
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
        )
        op.create_index("ix_alert_rules_project_id", "alert_rules", ["project_id"])
    if "alert_events" not in existing:
        op.create_table(
            "alert_events",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("rule_id", sa.Uuid(), nullable=False),
            sa.Column("project_id", sa.Uuid(), nullable=False),
            sa.Column("kind", sa.String(length=16), nullable=False),
            sa.Column("value", sa.Float(), nullable=True),
            sa.Column("threshold", sa.Float(), nullable=False),
            sa.Column("message", sa.String(length=2000), nullable=False),
            sa.Column("delivery_status", sa.String(length=16), nullable=False),
            sa.Column("delivery_error", sa.String(length=2000), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=now_server_default(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["rule_id"], ["alert_rules.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_alert_events_project_created_at", "alert_events", ["project_id", "created_at"]
        )
        op.create_index("ix_alert_events_rule_id", "alert_events", ["rule_id"])


def downgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "alert_events" in existing:
        op.drop_index("ix_alert_events_rule_id", table_name="alert_events")
        op.drop_index("ix_alert_events_project_created_at", table_name="alert_events")
        op.drop_table("alert_events")
    if "alert_rules" in existing:
        op.drop_index("ix_alert_rules_project_id", table_name="alert_rules")
        op.drop_table("alert_rules")

"""conversations and conversation_scores

Revision ID: 0027_conversations
Revises: 0026_system_llm_settings
Create Date: 2026-11-09
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

revision: str = "0027_conversations"
down_revision: str | None = "0026_system_llm_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("conversations"):
        op.create_table(
            "conversations",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("project_id", sa.Uuid(), nullable=False),
            sa.Column("session_id", sa.String(length=200), nullable=False),
            sa.Column("user_id", sa.String(length=200), nullable=True),
            sa.Column("environment", sa.String(length=64), nullable=True),
            sa.Column("turn_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("judge_status", sa.String(length=32), nullable=False),
            sa.Column("metrics_set_id", sa.Uuid(), nullable=True),
            sa.Column("score_warning", sa.Text(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
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
            sa.Column("scored_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["metrics_set_id"],
                ["metrics_sets.id"],
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "project_id",
                "session_id",
                name="uq_conversations_project_session_id",
            ),
        )
        op.create_index(
            "ix_conversations_project_last_activity",
            "conversations",
            ["project_id", "last_activity_at"],
        )
        op.create_index(
            "ix_conversations_project_judge_status",
            "conversations",
            ["project_id", "judge_status"],
        )

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("conversation_scores"):
        op.create_table(
            "conversation_scores",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("conversation_id", sa.Uuid(), nullable=False),
            sa.Column("evaluator_id", sa.Uuid(), nullable=True),
            sa.Column("kind", sa.String(length=64), nullable=False),
            sa.Column("score", sa.Float(), nullable=True),
            sa.Column("label", sa.String(length=64), nullable=True),
            sa.Column("explanation", sa.Text(), nullable=True),
            sa.Column("threshold", sa.Float(), nullable=True),
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
            sa.ForeignKeyConstraint(
                ["conversation_id"],
                ["conversations.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["evaluator_id"],
                ["evaluators.id"],
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_conversation_scores_conversation_id",
            "conversation_scores",
            ["conversation_id"],
        )


def downgrade() -> None:
    op.drop_table("conversation_scores")
    op.drop_table("conversations")

"""live interactions (AI Eval Run)

Revision ID: 0010_live_interactions
Revises: 0009_metrics_sets
Create Date: 2026-10-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_live_interactions"
down_revision: str | None = "0009_metrics_sets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("live_interactions"):
        op.create_table(
            "live_interactions",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("project_id", sa.Uuid(), nullable=False),
            sa.Column("question", sa.Text(), nullable=False),
            sa.Column("answer", sa.Text(), nullable=False),
            sa.Column(
                "documents",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "metadata",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("external_id", sa.String(length=200), nullable=True),
            sa.Column("judge_status", sa.String(length=32), nullable=False),
            sa.Column("metrics_set_id", sa.Uuid(), nullable=True),
            sa.Column("score_warning", sa.Text(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
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
                "external_id",
                name="uq_live_interactions_project_external_id",
            ),
        )
        op.create_index(
            "ix_live_interactions_project_created_at",
            "live_interactions",
            ["project_id", "created_at"],
        )
        op.create_index(
            "ix_live_interactions_project_judge_status",
            "live_interactions",
            ["project_id", "judge_status"],
        )

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("live_interaction_scores"):
        op.create_table(
            "live_interaction_scores",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("live_interaction_id", sa.Uuid(), nullable=False),
            sa.Column("evaluator_id", sa.Uuid(), nullable=True),
            sa.Column("kind", sa.String(length=64), nullable=False),
            sa.Column("score", sa.Float(), nullable=True),
            sa.Column("label", sa.String(length=64), nullable=True),
            sa.Column("explanation", sa.Text(), nullable=True),
            sa.Column("threshold", sa.Float(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["live_interaction_id"],
                ["live_interactions.id"],
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
            "ix_live_interaction_scores_interaction_id",
            "live_interaction_scores",
            ["live_interaction_id"],
        )

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("live_reviews"):
        op.create_table(
            "live_reviews",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("live_interaction_id", sa.Uuid(), nullable=False),
            sa.Column("verdict", sa.String(length=32), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("reviewer", sa.String(length=200), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["live_interaction_id"],
                ["live_interactions.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "live_interaction_id",
                name="uq_live_reviews_interaction_id",
            ),
        )


def downgrade() -> None:
    op.drop_table("live_reviews")
    op.drop_index(
        "ix_live_interaction_scores_interaction_id",
        table_name="live_interaction_scores",
    )
    op.drop_table("live_interaction_scores")
    op.drop_index(
        "ix_live_interactions_project_judge_status",
        table_name="live_interactions",
    )
    op.drop_index(
        "ix_live_interactions_project_created_at",
        table_name="live_interactions",
    )
    op.drop_table("live_interactions")

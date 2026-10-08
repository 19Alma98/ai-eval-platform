"""live score reviews for judge calibration

Revision ID: 0012_live_score_reviews
Revises: 0011_judge_claim_cache
Create Date: 2026-10-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_live_score_reviews"
down_revision: str | None = "0011_judge_claim_cache"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("live_score_reviews"):
        op.create_table(
            "live_score_reviews",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("live_interaction_score_id", sa.Uuid(), nullable=False),
            sa.Column("verdict", sa.String(length=32), nullable=False),
            sa.Column("corrected_explanation", sa.Text(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("reviewer", sa.String(length=200), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["live_interaction_score_id"],
                ["live_interaction_scores.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "live_interaction_score_id",
                name="uq_live_score_reviews_score_id",
            ),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("live_score_reviews"):
        op.drop_table("live_score_reviews")

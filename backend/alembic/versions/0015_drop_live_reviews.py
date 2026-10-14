"""drop interaction-level live_reviews

Revision ID: 0015_drop_live_reviews
Revises: 0014_trace_scores
Create Date: 2026-10-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_drop_live_reviews"
down_revision: str | None = "0014_trace_scores"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("live_reviews"):
        op.drop_table("live_reviews")


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("live_reviews"):
        return
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

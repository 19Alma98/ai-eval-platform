"""judge claim cache and live score metadata

Revision ID: 0011_judge_claim_cache
Revises: 0010_live_interactions
Create Date: 2026-10-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_judge_claim_cache"
down_revision: str | None = "0010_live_interactions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("judge_claim_cache"):
        op.create_table(
            "judge_claim_cache",
            sa.Column("key", sa.String(length=64), nullable=False),
            sa.Column("prompt_version", sa.String(length=128), nullable=False),
            sa.Column("model", sa.String(length=200), nullable=False),
            sa.Column("claims", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("key"),
        )

    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("live_interaction_scores")}
    if "metadata" not in columns:
        op.add_column(
            "live_interaction_scores",
            sa.Column(
                "metadata",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("live_interaction_scores"):
        columns = {c["name"] for c in inspector.get_columns("live_interaction_scores")}
        if "metadata" in columns:
            op.drop_column("live_interaction_scores", "metadata")

    if inspector.has_table("judge_claim_cache"):
        op.drop_table("judge_claim_cache")

"""create experiment_item_outputs

Revision ID: 0006_experiment_item_outputs
Revises: 0005_datasets_task_type
Create Date: 2026-10-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_experiment_item_outputs"
down_revision: str | None = "0005_datasets_task_type"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "experiment_item_outputs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("experiment_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_item_id", sa.Uuid(), nullable=False),
        sa.Column("actual_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["experiment_id"], ["experiments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dataset_item_id"], ["dataset_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "experiment_id",
            "dataset_item_id",
            name="uq_experiment_item_outputs_exp_item",
        ),
    )
    op.create_index(
        "ix_experiment_item_outputs_experiment_id",
        "experiment_item_outputs",
        ["experiment_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_experiment_item_outputs_experiment_id",
        table_name="experiment_item_outputs",
    )
    op.drop_table("experiment_item_outputs")

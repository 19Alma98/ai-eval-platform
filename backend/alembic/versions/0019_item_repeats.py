"""repeat index on experiment outputs and evaluation results

Revision ID: 0019_item_repeats
Revises: 0018_experiment_git
Create Date: 2026-10-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_item_repeats"
down_revision: str | None = "0018_experiment_git"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_UQ = "uq_experiment_item_outputs_exp_item"
_NEW_UQ = "uq_experiment_item_outputs_exp_item_repeat"


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "repeat" not in _columns("experiment_item_outputs"):
        with op.batch_alter_table("experiment_item_outputs") as batch_op:
            batch_op.add_column(
                sa.Column("repeat", sa.Integer(), nullable=False, server_default="0")
            )
            batch_op.drop_constraint(_OLD_UQ, type_="unique")
            batch_op.create_unique_constraint(
                _NEW_UQ, ["experiment_id", "dataset_item_id", "repeat"]
            )
    if "repeat" not in _columns("evaluation_results"):
        with op.batch_alter_table("evaluation_results") as batch_op:
            batch_op.add_column(
                sa.Column("repeat", sa.Integer(), nullable=False, server_default="0")
            )


def downgrade() -> None:
    if "repeat" in _columns("evaluation_results"):
        with op.batch_alter_table("evaluation_results") as batch_op:
            batch_op.drop_column("repeat")
    if "repeat" in _columns("experiment_item_outputs"):
        op.execute("DELETE FROM experiment_item_outputs WHERE repeat > 0")
        with op.batch_alter_table("experiment_item_outputs") as batch_op:
            batch_op.drop_constraint(_NEW_UQ, type_="unique")
            batch_op.create_unique_constraint(_OLD_UQ, ["experiment_id", "dataset_item_id"])
            batch_op.drop_column("repeat")

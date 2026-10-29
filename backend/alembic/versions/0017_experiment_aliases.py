"""experiment aliases (promoted baselines) and their history

Revision ID: 0017_experiment_aliases
Revises: 0016_sqlite_default_index
Create Date: 2026-10-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from opengrade_server.infrastructure.migration_helpers import now_server_default

revision: str = "0017_experiment_aliases"
down_revision: str | None = "0016_sqlite_default_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "experiment_aliases" not in existing:
        _create_aliases()
    if "experiment_alias_events" not in existing:
        _create_alias_events()


def _create_aliases() -> None:
    op.create_table(
        "experiment_aliases",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("experiment_id", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=now_server_default(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["experiment_id"], ["experiments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "name"),
    )
    op.create_index(
        "ix_experiment_aliases_experiment_id",
        "experiment_aliases",
        ["experiment_id"],
        unique=False,
    )


def _create_alias_events() -> None:
    op.create_table(
        "experiment_alias_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("experiment_id", sa.Uuid(), nullable=False),
        sa.Column("previous_experiment_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.String(length=2000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=now_server_default(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["experiment_id"], ["experiments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["previous_experiment_id"], ["experiments.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_experiment_alias_events_project_name_created_at",
        "experiment_alias_events",
        ["project_id", "name", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_experiment_alias_events_project_name_created_at",
        table_name="experiment_alias_events",
    )
    op.drop_table("experiment_alias_events")
    op.drop_index("ix_experiment_aliases_experiment_id", table_name="experiment_aliases")
    op.drop_table("experiment_aliases")

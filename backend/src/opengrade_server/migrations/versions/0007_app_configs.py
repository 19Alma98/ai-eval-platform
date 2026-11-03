"""app configs, aliases, experiment app_config_id

Revision ID: 0007_app_configs
Revises: 0006_experiment_item_outputs
Create Date: 2026-10-02
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

revision: str = "0007_app_configs"
down_revision: str | None = "0006_experiment_item_outputs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_configs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column(
            "prompt",
            portable_json(),
            server_default=json_server_default("{}"),
            nullable=False,
        ),
        sa.Column(
            "model",
            portable_json(),
            server_default=json_server_default("{}"),
            nullable=False,
        ),
        sa.Column(
            "retrieval",
            portable_json(),
            server_default=json_server_default("{}"),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=now_server_default(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "name",
            "version",
            name="uq_app_configs_project_name_version",
        ),
    )
    op.create_index(
        "ix_app_configs_project_name",
        "app_configs",
        ["project_id", "name"],
        unique=False,
    )
    op.create_index(
        "ix_app_configs_project_created_at",
        "app_configs",
        ["project_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "app_config_aliases",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("app_config_id", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=now_server_default(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["app_config_id"],
            ["app_configs.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "name"),
    )

    with op.batch_alter_table("experiments") as batch_op:
        batch_op.add_column(sa.Column("app_config_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_experiments_app_config_id_app_configs",
            "app_configs",
            ["app_config_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_experiments_app_config_id",
            ["app_config_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("experiments") as batch_op:
        batch_op.drop_index("ix_experiments_app_config_id")
        batch_op.drop_constraint(
            "fk_experiments_app_config_id_app_configs",
            type_="foreignkey",
        )
        batch_op.drop_column("app_config_id")
    op.drop_table("app_config_aliases")
    op.drop_index("ix_app_configs_project_created_at", table_name="app_configs")
    op.drop_index("ix_app_configs_project_name", table_name="app_configs")
    op.drop_table("app_configs")

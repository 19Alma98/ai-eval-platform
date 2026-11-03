"""metrics packs

Revision ID: 0008_metrics_packs
Revises: 0007_app_configs
Create Date: 2026-10-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from opengrade_server.infrastructure.migration_helpers import now_server_default, portable_json

revision: str = "0008_metrics_packs"
down_revision: str | None = "0007_app_configs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("metrics_packs"):
        return
    op.create_table(
        "metrics_packs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column(
            "entries",
            portable_json(),
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
        sa.UniqueConstraint("project_id", name="uq_metrics_packs_project_id"),
    )


def downgrade() -> None:
    op.drop_table("metrics_packs")

"""singleton LLM judge settings overlay (non-secret fields)

Revision ID: 0026_system_llm_settings
Revises: 0025_api_keys
Create Date: 2026-11-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from opengrade_server.infrastructure.migration_helpers import now_server_default

revision: str = "0026_system_llm_settings"
down_revision: str | None = "0025_api_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "system_llm_settings"


def upgrade() -> None:
    if _TABLE in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("api_base", sa.String(length=500), nullable=True),
        sa.Column("timeout_seconds", sa.Float(), nullable=True),
        sa.Column("max_retries", sa.Integer(), nullable=True),
        sa.Column("max_concurrency", sa.Integer(), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=now_server_default(),
        ),
        sa.CheckConstraint("id = 1", name="ck_system_llm_settings_singleton"),
    )


def downgrade() -> None:
    op.drop_table(_TABLE)

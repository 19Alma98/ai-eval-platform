"""make the SQLite one-default-per-project index partial

Revision ID: 0016_sqlite_default_index
Revises: 0015_drop_live_reviews
Create Date: 2026-10-20

0009 created ``uq_metrics_sets_one_project_default`` with only ``postgresql_where``,
so on SQLite it became UNIQUE(project_id): a project could hold a single metrics
set and every further create failed with 409. Recreate it as a partial index.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_sqlite_default_index"
down_revision: str | None = "0015_drop_live_reviews"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "uq_metrics_sets_one_project_default"


def _sqlite_index_sql() -> str | None:
    row = (
        op.get_bind()
        .execute(
            sa.text("SELECT sql FROM sqlite_master WHERE type = 'index' AND name = :name"),
            {"name": INDEX},
        )
        .first()
    )
    return None if row is None else str(row[0] or "")


def upgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    sql = _sqlite_index_sql()
    if sql is not None and "WHERE" in sql.upper():
        return  # already partial (fresh DB, or created by create_all)
    if sql is not None:
        op.drop_index(INDEX, table_name="metrics_sets")
    op.create_index(
        INDEX,
        "metrics_sets",
        ["project_id"],
        unique=True,
        sqlite_where=sa.text("is_project_default"),
    )


def downgrade() -> None:
    # The full-table unique index was a bug; keep the partial one.
    pass

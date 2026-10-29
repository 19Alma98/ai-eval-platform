"""git revision the experiment's code ran at

Revision ID: 0018_experiment_git
Revises: 0017_experiment_aliases
Create Date: 2026-10-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from opengrade_server.infrastructure.migration_helpers import portable_json

revision: str = "0018_experiment_git"
down_revision: str | None = "0017_experiment_aliases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_git_column() -> bool:
    columns = sa.inspect(op.get_bind()).get_columns("experiments")
    return any(c["name"] == "git" for c in columns)


def upgrade() -> None:
    if not _has_git_column():
        with op.batch_alter_table("experiments") as batch_op:
            batch_op.add_column(sa.Column("git", portable_json(), nullable=True))


def downgrade() -> None:
    if _has_git_column():
        with op.batch_alter_table("experiments") as batch_op:
            batch_op.drop_column("git")

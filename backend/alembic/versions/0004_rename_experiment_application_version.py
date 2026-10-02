"""rename experiments.application_version to version

Revision ID: 0004_rename_experiment_version
Revises: 0003_create_evaluation_tables
Create Date: 2026-10-02
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_rename_experiment_version"
down_revision: str | None = "0003_create_evaluation_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'experiments'
                  AND column_name = 'application_version'
            ) THEN
                ALTER TABLE experiments
                RENAME COLUMN application_version TO version;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'experiments'
                  AND column_name = 'version'
            ) AND NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'experiments'
                  AND column_name = 'application_version'
            ) THEN
                ALTER TABLE experiments
                RENAME COLUMN version TO application_version;
            END IF;
        END $$;
        """
    )

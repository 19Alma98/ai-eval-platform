"""versioned metrics sets (migrate from metrics_packs)

Revision ID: 0009_metrics_sets
Revises: 0008_metrics_packs
Create Date: 2026-10-05
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from uuid import UUID, uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_metrics_sets"
down_revision: str | None = "0008_metrics_packs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def entry_is_default(raw: dict) -> bool:
    return not bool(raw["removable"]) if "removable" in raw else False


def backfill_metrics_sets(connection) -> None:  # noqa: ANN001
    result = connection.execute(
        sa.text("SELECT id, project_id, entries FROM metrics_packs"),
    )
    for row in result.mappings().all():
        pack_id = row["id"]
        project_id = row["project_id"]
        entries = row["entries"] or []
        connection.execute(
            sa.text(
                """
                INSERT INTO metrics_sets
                    (id, project_id, name, version, is_project_default)
                VALUES
                    (:id, :project_id, :name, :version, :is_project_default)
                """
            ),
            {
                "id": pack_id,
                "project_id": project_id,
                "name": "Default",
                "version": 1,
                "is_project_default": True,
            },
        )
        for entry in entries:
            evaluator_id = entry.get("evaluator_id")
            if evaluator_id is not None:
                evaluator_id = UUID(str(evaluator_id))
            config = entry.get("config") or {}
            connection.execute(
                sa.text(
                    """
                    INSERT INTO metrics_set_entries
                        (id, metrics_set_id, kind, enabled, threshold, config,
                         evaluator_id, is_default)
                    VALUES
                        (:id, :metrics_set_id, :kind, :enabled, :threshold,
                         CAST(:config AS jsonb),
                         :evaluator_id, :is_default)
                    """
                ),
                {
                    "id": uuid4(),
                    "metrics_set_id": pack_id,
                    "kind": entry["kind"],
                    "enabled": entry.get("enabled", True),
                    "threshold": entry.get("threshold"),
                    "config": json.dumps(config),
                    "evaluator_id": evaluator_id,
                    "is_default": entry_is_default(entry),
                },
            )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    has_packs = inspector.has_table("metrics_packs")

    if not inspector.has_table("metrics_sets"):
        op.create_table(
            "metrics_sets",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("project_id", sa.Uuid(), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("version", sa.Integer(), server_default="1", nullable=False),
            sa.Column("description", sa.String(length=2000), nullable=True),
            sa.Column(
                "is_project_default",
                sa.Boolean(),
                server_default=sa.text("false"),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "project_id",
                "name",
                "version",
                name="uq_metrics_sets_project_name_version",
            ),
        )
        op.create_index(
            "uq_metrics_sets_one_project_default",
            "metrics_sets",
            ["project_id"],
            unique=True,
            postgresql_where=sa.text("is_project_default"),
        )

    if not inspector.has_table("metrics_set_entries"):
        op.create_table(
            "metrics_set_entries",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("metrics_set_id", sa.Uuid(), nullable=False),
            sa.Column("kind", sa.String(length=64), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("threshold", sa.Float(), nullable=True),
            sa.Column(
                "config",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
            sa.Column("evaluator_id", sa.Uuid(), nullable=True),
            sa.Column(
                "is_default",
                sa.Boolean(),
                server_default=sa.text("false"),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["metrics_set_id"],
                ["metrics_sets.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["evaluator_id"],
                ["evaluators.id"],
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "metrics_set_id",
                "kind",
                name="uq_metrics_set_entries_set_kind",
            ),
        )

    if has_packs:
        backfill_metrics_sets(bind)

    op.add_column("experiments", sa.Column("metrics_set_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_experiments_metrics_set_id",
        "experiments",
        "metrics_sets",
        ["metrics_set_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    if has_packs:
        op.drop_table("metrics_packs")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("metrics_packs") and inspector.has_table("metrics_sets"):
        op.create_table(
            "metrics_packs",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("project_id", sa.Uuid(), nullable=False),
            sa.Column(
                "entries",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("project_id", name="uq_metrics_packs_project_id"),
        )

        sets_result = bind.execute(
            sa.text(
                """
                SELECT id, project_id, updated_at
                FROM metrics_sets
                WHERE is_project_default IS TRUE
                """
            ),
        )
        for ms in sets_result.mappings().all():
            entries_result = bind.execute(
                sa.text(
                    """
                    SELECT kind, enabled, threshold, config, evaluator_id, is_default
                    FROM metrics_set_entries
                    WHERE metrics_set_id = :metrics_set_id
                    ORDER BY kind
                    """
                ),
                {"metrics_set_id": ms["id"]},
            )
            entries: list[dict] = []
            for entry in entries_result.mappings().all():
                raw: dict = {
                    "kind": entry["kind"],
                    "enabled": entry["enabled"],
                    "threshold": entry["threshold"],
                    "config": entry["config"] or {},
                    "removable": not entry["is_default"],
                }
                if entry["evaluator_id"] is not None:
                    raw["evaluator_id"] = str(entry["evaluator_id"])
                entries.append(raw)
            bind.execute(
                sa.text(
                    """
                    INSERT INTO metrics_packs (id, project_id, entries, updated_at)
                    VALUES (:id, :project_id, CAST(:entries AS jsonb), :updated_at)
                    """
                ),
                {
                    "id": ms["id"],
                    "project_id": ms["project_id"],
                    "entries": json.dumps(entries),
                    "updated_at": ms["updated_at"],
                },
            )

    op.drop_constraint("fk_experiments_metrics_set_id", "experiments", type_="foreignkey")
    op.drop_column("experiments", "metrics_set_id")

    if inspector.has_table("metrics_set_entries"):
        op.drop_table("metrics_set_entries")
    if inspector.has_table("metrics_sets"):
        op.drop_index(
            "uq_metrics_sets_one_project_default",
            table_name="metrics_sets",
        )
        op.drop_table("metrics_sets")
from __future__ import annotations

import importlib.util

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from opengrade_server.infrastructure.db import MIGRATIONS_DIR


def _load_revision():
    path = MIGRATIONS_DIR / "versions" / "0004_rename_experiment_application_version.py"
    spec = importlib.util.spec_from_file_location("rev_0004_rename", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _columns(conn: sa.Connection) -> set[str]:
    return {c["name"] for c in sa.inspect(conn).get_columns("experiments")}


def test_upgrade_and_downgrade_rename_the_column(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_revision()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE experiments (id INTEGER, application_version TEXT)"))
        conn.execute(sa.text("INSERT INTO experiments VALUES (1, 'v1')"))
        ops = Operations(MigrationContext.configure(conn))
        monkeypatch.setattr(module, "op", ops)

        module.upgrade()
        assert _columns(conn) == {"id", "version"}
        assert conn.execute(sa.text("SELECT version FROM experiments")).scalar() == "v1"
        module.upgrade()  # idempotent: already renamed
        assert _columns(conn) == {"id", "version"}

        module.downgrade()
        assert _columns(conn) == {"id", "application_version"}

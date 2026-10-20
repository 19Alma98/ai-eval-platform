"""Postgres migration path serializes upgrades with an advisory lock."""

from __future__ import annotations

import zlib

from opengrade_server.infrastructure import db
from opengrade_server.infrastructure.db import (
    MIGRATION_ADVISORY_LOCK_KEY,
    _postgres_locked_upgrade,
)


class _FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object | None, object | None]] = []

    def execute(self, statement: object, params: object | None = None) -> None:
        self.calls.append(("execute", str(statement), params))

    def commit(self) -> None:
        self.calls.append(("commit", None, None))


def test_postgres_locked_upgrade_lock_upgrade_unlock_order(monkeypatch) -> None:
    conn = _FakeConnection()
    monkeypatch.setattr(
        db,
        "_upgrade_alembic_on_connection",
        lambda _c: conn.calls.append(("upgrade", None, None)),
    )

    _postgres_locked_upgrade(conn)  # type: ignore[arg-type]

    kinds = [c[0] for c in conn.calls]
    assert kinds == [
        "execute",
        "commit",
        "upgrade",
        "commit",
        "execute",
        "commit",
    ]
    lock_sql, lock_params = conn.calls[0][1], conn.calls[0][2]
    unlock_sql, unlock_params = conn.calls[4][1], conn.calls[4][2]
    assert "pg_advisory_lock" in str(lock_sql)
    assert "pg_advisory_unlock" in str(unlock_sql)
    assert lock_params == {"key": MIGRATION_ADVISORY_LOCK_KEY}
    assert unlock_params == {"key": MIGRATION_ADVISORY_LOCK_KEY}


def test_postgres_locked_upgrade_unlocks_when_upgrade_fails(monkeypatch) -> None:
    conn = _FakeConnection()

    def _boom(_c: object) -> None:
        conn.calls.append(("upgrade", None, None))
        raise RuntimeError("migration failed")

    monkeypatch.setattr(db, "_upgrade_alembic_on_connection", _boom)

    try:
        _postgres_locked_upgrade(conn)  # type: ignore[arg-type]
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError")

    kinds = [c[0] for c in conn.calls]
    assert kinds[0] == "execute"
    assert "pg_advisory_lock" in str(conn.calls[0][1])
    assert "upgrade" in kinds
    assert kinds[-2] == "execute"
    assert "pg_advisory_unlock" in str(conn.calls[-2][1])
    assert kinds[-1] == "commit"


def test_migration_lock_key_is_stable() -> None:
    assert MIGRATION_ADVISORY_LOCK_KEY == zlib.crc32(b"opengrade_migrations")

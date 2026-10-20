from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import TextClause


def portable_json() -> sa.JSON[Any]:
    """JSON on SQLite; JSONB on Postgres (matches ORM ``PortableJSON``)."""
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _bind_dialect_name() -> str:
    """Dialect name for the current Alembic bind, or empty if unavailable (unit tests)."""
    bind = op.get_bind()
    dialect = getattr(bind, "dialect", None)
    name = getattr(dialect, "name", None)
    return name if isinstance(name, str) else ""


def json_server_default(empty: str = "{}") -> TextClause:
    """Server default for JSON/JSONB columns (``{}`` or ``[]``)."""
    if _bind_dialect_name() == "postgresql":
        return sa.text(f"'{empty}'::jsonb")
    return sa.text(f"'{empty}'")


def now_server_default() -> TextClause:
    """Timezone-aware-friendly now() / CURRENT_TIMESTAMP across dialects."""
    if _bind_dialect_name() == "postgresql":
        return sa.text("now()")
    return sa.text("(CURRENT_TIMESTAMP)")

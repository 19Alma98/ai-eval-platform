"""Apply database migrations (Docker entrypoint and ops)."""

from __future__ import annotations

from opengrade_server.infrastructure.db import run_migrations


def main() -> None:
    run_migrations()


if __name__ == "__main__":
    main()

# opengrade-ai-server

OpenGrade server package (API + packaged UI).

- Distribution: `opengrade-ai-server` (PyPI)
- Import path: `opengrade_server` (e.g. `uvicorn opengrade_server.main:app`)
- Console scripts: `opengrade` (`ui`, `check`; provided by the `opengrade-ai` dependency) and `opengrade-server` (same commands)

## Local UI

Requires Node.js >= 22 to build the UI from a clone. Contributors should use `uv sync --all-extras` (plain `uv sync` strips extras from an existing venv).

```bash
# from repo root — build the Next static export into the package
python scripts/package_ui.py   # or ./scripts/package-ui.sh
cd backend && uv sync --all-extras
uv run opengrade ui
# → http://127.0.0.1:8000  (SQLite ./opengrade.db by default)
```

Local SQLite schema is applied with Alembic on startup (same revisions as Postgres). File-backed SQLite uses WAL and a 5s `busy_timeout`. If a pre-Alembic DB is stale (schema behind models), delete `./opengrade.db` (and any `-wal`/`-shm` sidecars) and restart.

**Backup:** stop the process (or run `PRAGMA wal_checkpoint(FULL)`), then copy `opengrade.db` plus any `opengrade.db-wal` / `opengrade.db-shm` files. Do not copy only the main file while the process is writing under WAL.

`opengrade ui` loads `.env` from the current working directory when present, prints LLM / content-capture settings, and exits if the bind port already has a listener (use `--port` or stop the other process).

Postgres:

```bash
uv run opengrade ui --backend-store-uri 'postgresql+asyncpg://opengrade:opengrade@localhost:5434/opengrade'
```

## Ops (container)

- **Single API replica** — scoring runs in-process; multi-replica recovery is not safe yet.
- Probes: `GET /health` (liveness), `GET /ready` (DB readiness). Compose healthchecks `/ready`.
- Requests carry `X-Request-ID` (echoed / generated).
- Entrypoint: `--proxy-headers`, `--forwarded-allow-ips` (`FORWARDED_ALLOW_IPS`), `--timeout-graceful-shutdown` (`SHUTDOWN_GRACE_SECONDS`).
- OTLP `/v1/traces` may return **429** / **503** with `Retry-After` when rate, inflight, or pending-score caps are hit (`OTLP_*` in `.env.example`).

See the repository root README for Docker Compose and SDK quickstart. Compose loads `backend/.env` when present (`env_file` is optional); copy from `.env.example` for LLM judges and other overrides.

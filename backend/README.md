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

Local SQLite schema is applied with Alembic on startup (same revisions as Postgres). File-backed SQLite uses WAL and a 5s `busy_timeout`. If a local DB is stale or broken, delete `./opengrade.db` (and any `-wal`/`-shm` sidecars) and restart.

**Backup:** stop the process (or run `PRAGMA wal_checkpoint(FULL)`), then copy `opengrade.db` plus any `opengrade.db-wal` / `opengrade.db-shm` files. Do not copy only the main file while the process is writing under WAL.

`opengrade ui` loads `.env` from the current working directory when present, prints LLM / content-capture settings, and exits if the bind port already has a listener (use `--port` or stop the other process).

Postgres:

```bash
uv run opengrade ui --backend-store-uri 'postgresql+asyncpg://opengrade:opengrade@localhost:5434/opengrade'
```

## Ops (container)

- **Image:** `ghcr.io/19alma98/ai-eval-platform/opengrade` (tags: semver from the release tag, plus `latest`). Published by [`.github/workflows/publish.yml`](../.github/workflows/publish.yml). Compose uses that image and can still `build:` from this checkout (`docker compose up --build`).
- **Single API replica** — scoring runs in-process; multi-replica recovery is not safe yet.
- Image runs as non-root (`opengrade`, uid/gid `10001`); `/app` is writable for optional SQLite and judge-prompt snapshots (`OPENGRADE_JUDGE_PROMPT_SNAPSHOTS`).
- Probes: `GET /health` (liveness), `GET /ready` (DB readiness). Compose healthchecks `/ready`.
- Requests carry `X-Request-ID` (echoed / generated).
- Entrypoint: `--proxy-headers`, `--forwarded-allow-ips` (`FORWARDED_ALLOW_IPS`), `--timeout-graceful-shutdown` (`SHUTDOWN_GRACE_SECONDS`).
- OTLP `/v1/traces` may return **429** / **503** with `Retry-After` when rate, inflight, or pending-score caps are hit (`OTLP_*` in `.env.example`).

### Environment variables

Settings are loaded from the process environment (and `.env` in the cwd when present). Compose
overrides `DATABASE_URL` for the `api` service and optionally loads `backend/.env`. Canonical
defaults and comments: [`.env.example`](.env.example). Field mapping lives in
`opengrade_server.config.Settings`.

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./opengrade.db` | Compose sets Postgres; use `postgresql+asyncpg://…` |
| `APP_HOST` / `APP_PORT` | `0.0.0.0` / `8000` | Container bind; Compose publishes `127.0.0.1:8000` |
| `CONTENT_CAPTURE_ENABLED` | `true` | `false` redacts span/LLM text at ingest |
| `OPENGRADE_API_KEY` | unset | Bootstrap admin key; unset = no auth |
| `OPENGRADE_UI_SESSION_HOURS` | `12` | UI session cookie lifetime |
| `LLM_MODEL` / `LLM_API_KEY` / `LLM_API_BASE` | see `.env.example` | LiteLLM judges; non-secret fields can be overridden in **Settings → LLM judges** (DB overlay). `LLM_API_KEY` is never stored in the DB — the UI writes it to cwd `.env` only. |
| `LLM_TIMEOUT_SECONDS` / `LLM_MAX_RETRIES` / `LLM_MAX_CONCURRENCY` | `60` / `2` / `8` | Raise timeout for cold Ollama; overridable in Settings |
| `LLM_TEMPERATURE` / `LLM_SEED` | `0.0` / `42` | Seed ignored by some providers; overridable in Settings |
| `FORWARDED_ALLOW_IPS` | `*` | Trusted proxies for `X-Forwarded-*` |
| `SHUTDOWN_GRACE_SECONDS` | `30` | Uvicorn graceful shutdown |
| `PUBLIC_BASE_URL` | unset | External UI URL in alert links |
| `ALERT_WEBHOOK_URL` | unset | Default webhook for alert rules |
| `ALERTS_ENABLED` / `ALERTS_INTERVAL_SECONDS` | `true` / `60` | In-process alert evaluation |
| `RETENTION_DAYS` / `RETENTION_INTERVAL_HOURS` | unset / `24` | Unset retention = keep forever |
| `OTLP_MAX_BODY_BYTES` / `JSON_MAX_BODY_BYTES` / `DATASET_IMPORT_MAX_BYTES` | 4 MiB | Request size caps |
| `OTLP_RATE_LIMIT_PER_SECOND` / `OTLP_MAX_INFLIGHT` / `OTLP_MAX_PENDING_SCORES` / `OTLP_RETRY_AFTER_SECONDS` | `50` / `32` / `200` / `1` | Per-process backpressure |
| `OPENGRADE_JUDGE_PROMPT_SNAPSHOTS` | `.opengrade/judge_prompt_snapshots.json` | Local audit file under cwd |

See the repository root README for Docker Compose and SDK quickstart.

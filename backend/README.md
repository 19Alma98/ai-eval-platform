# opengrade-ai-server

Server package for the AI Evaluation & Observability Platform.

- Distribution: `opengrade-ai-server` (PyPI)
- Import path: `opengrade_server` (e.g. `uvicorn opengrade_server.main:app`)
- Console scripts: `opengrade` (`ui`, `check`; provided by the `opengrade-ai` dependency) and `opengrade-server` (same commands)

## Local UI

```bash
# from repo root — build the Next static export into the package
./scripts/package-ui.sh
cd backend && uv sync
uv run opengrade ui
# → http://127.0.0.1:8000  (SQLite ./opengrade.db by default)
```

Postgres:

```bash
uv run opengrade ui --backend-store-uri 'postgresql+asyncpg://opengrade:opengrade@localhost:5434/opengrade'
```

See the repository root README for Docker Compose and SDK quickstart.

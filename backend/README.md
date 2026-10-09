# aiobs-eval-server

Server package for the AI Evaluation & Observability Platform.

- Distribution: `aiobs-eval-server` (PyPI)
- Import path: `aiobs_server` (e.g. `uvicorn aiobs_server.main:app`)
- Console script: `aiobs` (`ui`, `check`)

## Local UI (MLflow-style)

```bash
# from repo root — build the Next static export into the package
./scripts/package-ui.sh
cd backend && uv sync
uv run aiobs ui
# → http://127.0.0.1:8000  (SQLite ./aiobs.db by default)
```

Postgres:

```bash
uv run aiobs ui --backend-store-uri 'postgresql+asyncpg://aiobs:aiobs@localhost:5434/aiobs'
```

See the repository root README for Docker Compose and SDK quickstart.

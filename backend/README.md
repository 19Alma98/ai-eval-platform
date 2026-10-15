# opengrade-ai-server

Server package for the AI Evaluation & Observability Platform.

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

`opengrade ui` loads `.env` from the current working directory when present, prints LLM / content-capture settings, and exits if the bind port already has a listener (use `--port` or stop the other process).

Postgres:

```bash
uv run opengrade ui --backend-store-uri 'postgresql+asyncpg://opengrade:opengrade@localhost:5434/opengrade'
```

See the repository root README for Docker Compose and SDK quickstart.

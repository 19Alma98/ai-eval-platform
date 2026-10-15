# OpenGrade UI

Next.js (App Router) frontend for the AI Evaluation & Observability Platform. Production builds are a static export served by `opengrade ui` / the server wheel from `backend/src/opengrade_server/_ui`.

**Requires Node.js >= 22.**

## Local development

```bash
npm ci
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The Next dev server proxies `/api` (and related paths) to `API_ORIGIN` (default in config: the local platform API, typically `http://127.0.0.1:8000`). Start the API separately (`opengrade ui` or Compose) so the UI can talk to it.

Useful scripts: `npm run lint`, `npm run typecheck`, `npm run test`.

## Package into the server (clone / release)

From the repo root (cross-platform; needs npm in `PATH`):

```bash
python scripts/package_ui.py
# equivalent on Unix CI: ./scripts/package-ui.sh
```

This runs `npm ci` + `npm run build` and copies `frontend/out/` into `backend/src/opengrade_server/_ui/`. Then from `backend/`:

```bash
uv sync --all-extras
uv run opengrade ui
```

PyPI installs of `opengrade-ai[ui]` already include the packaged UI — no Node build required for end users.

See the [repository root README](../README.md) and [backend/README.md](../backend/README.md) for quickstart and Docker Compose.

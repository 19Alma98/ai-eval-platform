# OpenGrade

Self-hosted AI evaluation & observability — traces, datasets, experiments, CI gates.

Open-source platform for AI quality engineering: turn production traces into datasets, run experiments, compare against a baseline, and fail CI on regressions. Packages: `opengrade-ai` (SDK) and `opengrade-ai-server` (API + UI); CLI `opengrade`.

**Best fit:** RAG/FAQ, classification, structured extraction, tool calling with fixed schemas, plus latency/cost/error gates.  
**Not a fit:** open-ended agents where “good” is subjective, or as a substitute for live APM. The platform measures what you define; it does not invent a quality oracle. Details: [`docs/00-project-overview.md`](docs/00-project-overview.md).

**Deployment model (v0.1):** trusted network only (localhost / private Docker network). There is **no built-in authentication**. Do not expose the stack on a public network without an external auth layer (reverse proxy, VPN, or cluster network policy).

![OpenGrade walkthrough: overview, traces, experiments, baseline compare, quality gate, production judge](docs/images/hero.gif)

**[Get started in 15 minutes →](docs/getting-started.md)** — `uv` + `opengrade ui`, first trace, optional scored experiment.

## Quickstart (local UI)

Zero external infra — SQLite file + packaged UI in one process:

```bash
uv add 'opengrade-ai[ui]'
uv run opengrade ui   # http://127.0.0.1:8000 → ./opengrade.db
```

Pip: `pip install 'opengrade-ai[ui]'` then `opengrade ui` (same URL and `./opengrade.db`).

From a fresh clone (Node.js >= 22 required for the UI build): `python scripts/package_ui.py`, then install/sync the backend and run `opengrade ui`. The CLI fails if port 8000 is already in use (e.g. Docker); pass `--port` or stop the other process. It loads `.env` from the current working directory when present and prints judge / content-capture settings at startup. Schema upgrades run automatically via Alembic; see [`backend/README.md`](backend/README.md) for SQLite backup notes (WAL).

Optional Postgres (production / Compose):

```bash
opengrade ui --backend-store-uri 'postgresql+asyncpg://opengrade:opengrade@localhost:5434/opengrade'
```

## Quickstart (Docker Compose)

Adopter-first path: follow [`docs/getting-started.md`](docs/getting-started.md) (`uv` + local UI, then optional experiment). Use Compose when you want Postgres and the full stack in containers.

```bash
cp backend/.env.example backend/.env   # optional but recommended
docker compose up --build
```
Copy the example when you want LLM judges or other overrides from [`backend/.env.example`](backend/.env.example). Without a configured judge (`LLM_API_KEY` for cloud, or Ollama + `LLM_MODEL` / `LLM_API_BASE`), the UI and OTLP ingest still work; LLM-judge metrics show as unavailable until you set one.

For local Ollama as judge while the API runs in Compose, uncomment in `backend/.env`:

```bash
LLM_MODEL=ollama/gemma4:e2b
LLM_API_BASE=http://host.docker.internal:11434
```

UI and API: http://127.0.0.1:8000 — one image serves both (the same static UI that `opengrade ui` ships). Compose publishes the API and Postgres (`127.0.0.1:5434`) on localhost only; change the port mappings to `"8000:8000"` / `"5434:5432"` if you intentionally need LAN access. For UI development run `npm run dev` in `frontend/` (http://localhost:3000, proxies `/api` to `API_ORIGIN`).

Check liveness / readiness (single API replica only — do not scale `api` without a shared job queue):

```bash
curl http://localhost:8000/health   # liveness
curl http://localhost:8000/ready    # DB readiness (Compose healthcheck)
```

Behind a reverse proxy, set `FORWARDED_ALLOW_IPS`. OTLP ingest may return `429`/`503` with `Retry-After` under load (see `backend/.env.example`).

### Portfolio demo (People Ops assistant + Ollama)

Dataset-first RAG loop: gold test set → metrics pack → `opengrade.evaluate` experiment per model (traces bound per item, outputs uploaded, pack scored) → compare → quality gate. Compares two local models (`OLLAMA_MODEL1` vs `OLLAMA_MODEL2`) on the same test set and pipeline.

1. `cp backend/.env.example backend/.env`, then `docker compose up --build`
2. Pull two chat models, e.g. `ollama pull gemma4:e2b` and `ollama pull tinyllama`
3. Sync SDK: `cd sdk && uv sync --extra openai && cd ..`
4. Sync server/CLI: `cd backend && uv sync --all-extras && cd ..`
5. Run: `python scripts/portfolio_demo.py`

In the UI: **Test set → Metrics → Runs**. Release policy uses pack names: `hit_at_k`, `groundedness`, `correctness`, `latency`.

**Live runs (prod-sim):** with API + LLM judge up, run `cd sdk && uv run python ../scripts/live_run_demo.py` then open **Live runs** in the UI (`/live-runs`).

Details: [`examples/hr_it_assistant/README.md`](examples/hr_it_assistant/README.md). Naming and glossary: [`docs/README.md`](docs/README.md).

Create a project:

```bash
curl -X POST http://localhost:8000/api/v1/projects \
  -H "content-type: application/json" \
  -d "{\"name\":\"Demo\",\"slug\":\"demo\"}"
```

List projects:

```bash
curl http://localhost:8000/api/v1/projects
```

### Ingest a trace (OTLP/HTTP)

Send OTLP JSON or protobuf to `POST /v1/traces` with exactly one of `X-Project-Id` or `X-Project-Slug`:

```bash
curl -X POST http://localhost:8000/v1/traces \
  -H "content-type: application/json" \
  -H "X-Project-Slug: demo" \
  -d "{\"resourceSpans\":[{\"scopeSpans\":[{\"spans\":[{\"traceId\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\",\"spanId\":\"bbbbbbbbbbbbbbbb\",\"name\":\"hello\",\"startTimeUnixNano\":\"1700000000000000000\",\"endTimeUnixNano\":\"1700000001000000000\",\"status\":{\"code\":\"STATUS_CODE_OK\"},\"attributes\":[{\"key\":\"openinference.span.kind\",\"value\":{\"stringValue\":\"CHAIN\"}}]}]}]}]}"
```

Or run the Python example:

```bash
cd examples/otlp_hello
pip install -r requirements.txt
set OPENGRADE_PROJECT_SLUG=demo
python main.py
```

### Instrument with Python SDK

```bash
cd sdk && uv sync --extra openai && cd ..
# see examples/sdk_hello/README.md
```

Package docs: [`sdk/README.md`](sdk/README.md).

### Get trace by id

After OTLP ingest, fetch one trace (e.g. for Run timeline binding):

```bash
curl "http://localhost:8000/api/v1/projects/<project-uuid>/traces/<otel-trace-id-hex>"
```

## Quality gate (Phase 4)

After evaluating an experiment, check a YAML policy:

```bash
cd backend && uv sync --all-extras
uv run opengrade check --policy ../examples/opengrade.yaml \
  --base-url http://localhost:8000 \
  --project-id <project-uuid> \
  --experiment-id <experiment-uuid>
```

Exit codes: `0` pass, `1` gate failed, `2` config error, `3` infra error. Example workflow: [`.github/workflows/release-gate.yml.example`](.github/workflows/release-gate.yml.example).

## PyPI release

Packages: **`opengrade-ai`** (SDK) and **`opengrade-ai-server`** (API + UI). Publish via tag `vX.Y.Z` and [`.github/workflows/publish.yml`](.github/workflows/publish.yml) (Trusted Publishing). Setup and checklist: [`docs/08-cli-ci.md`](docs/08-cli-ci.md#publishing-to-pypi).

## Development (backend)

```bash
cd backend
cp .env.example .env   # edit as needed (Compose-oriented values; see warnings from opengrade ui)
uv sync --all-extras   # plain `uv sync` strips extras from an existing venv
uv run alembic upgrade head
uv run uvicorn opengrade_server.main:app --reload --host 0.0.0.0 --port 8000
```

For the packaged UI from a clone: from repo root run `python scripts/package_ui.py` (or `./scripts/package-ui.sh`), then `uv run opengrade ui` from `backend/`.

Requires PostgreSQL. With Compose, Postgres is published on host port **5434** (`DATABASE_URL=postgresql+asyncpg://opengrade:opengrade@localhost:5434/opengrade`).

### LLM judges (LiteLLM / Ollama)

LLM judges use LiteLLM. Settings live in `backend/.env` (see `.env.example`). For local Ollama the example sets:

```bash
LLM_MODEL=ollama/gemma4:e2b
LLM_API_BASE=http://localhost:11434
```

When creating an evaluator, use `"type": "llm_judge"` and `"config": {"kind": "correctness"}` (or `answer_relevance` / `groundedness` / `context_precision` / `context_recall`).

### RAG metrics naming

| opengrade `kind` | Notes |
|---|---|
| `groundedness` | Answer claims supported by retrieved docs |
| `answer_relevance` | Question–answer relevance (rubric) |
| `context_precision` | RAGAS-style average precision over retrieved docs |
| `context_recall` | Gold-answer claims covered by retrieved docs |
| `correctness` | Gold claims covered by the answer |
| `hit_at_k` / `recall_at_k` / `mrr` | Deterministic retrieval metrics on `expected_doc_ids` |

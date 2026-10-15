# AI Evaluation & Observability Platform

Open-source, self-hosted platform for AI quality engineering: turn production traces into datasets, run experiments, compare against a baseline, and fail CI on regressions.

**Best fit:** RAG/FAQ, classification, structured extraction, tool calling with fixed schemas, plus latency/cost/error gates.  
**Not a fit:** open-ended agents where “good” is subjective, or as a substitute for live APM. The platform measures what you define; it does not invent a quality oracle. Details: [`docs/00-project-overview.md`](docs/00-project-overview.md).

**Deployment model (v0.1):** trusted network only (localhost / private Docker network). There is **no built-in authentication**. Do not expose the stack on a public network without an external auth layer (reverse proxy, VPN, or cluster network policy).

## Quickstart (local UI)

Zero external infra — SQLite file + packaged UI in one process:

```bash
# from a built/release install, or after ./scripts/package-ui.sh + pip install -e backend
pip install 'opengrade-ai[ui]'   # SDK + opengrade-ai-server (includes UI)
opengrade ui                       # http://127.0.0.1:8000  → creates ./opengrade.db
```

Optional Postgres (production / Compose):

```bash
opengrade ui --backend-store-uri 'postgresql+asyncpg://opengrade:opengrade@localhost:5434/opengrade'
```

## Quickstart (Docker Compose)

```bash
docker compose up --build
```

UI and API: http://localhost:8000 — one image serves both (the same static UI that `opengrade ui` ships). For UI development run `npm run dev` in `frontend/` (http://localhost:3000, proxies `/api` to `API_ORIGIN`).

Check health:

```bash
curl http://localhost:8000/health
```

### Portfolio demo (People Ops assistant + Ollama)

Dataset-first RAG loop: gold test set → metrics pack → `opengrade.evaluate` experiment per model (traces bound per item, outputs uploaded, pack scored) → compare → release gate. Compares two local models (`OLLAMA_MODEL1` vs `OLLAMA_MODEL2`) on the same test set and pipeline.

1. `docker compose up --build`
2. Pull two chat models, e.g. `ollama pull gemma4:e2b` and `ollama pull tinyllama`
3. Sync SDK: `cd sdk && uv sync --extra openai && cd ..`
4. Sync server/CLI: `cd backend && uv sync && cd ..`
5. Run: `python scripts/portfolio_demo.py`

In the UI: **Test set → Metriche → Runs**. Release policy uses pack names: `hit_at_k`, `groundedness`, `correctness`, `latency`.

**AI Eval Run (prod-sim):** with API + LLM judge up, run `cd sdk && uv run python ../scripts/live_run_demo.py` then open **Live runs** in the UI (`/live-runs`).

Details: [`examples/hr_it_assistant/README.md`](examples/hr_it_assistant/README.md). RAG vertical: [`docs/superpowers/specs/2026-10-05-rag-eval-dataset-first-design.md`](docs/superpowers/specs/2026-10-05-rag-eval-dataset-first-design.md).

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

## Release gate (Phase 4)

After evaluating an experiment, check a YAML policy:

```bash
cd backend && uv sync
uv run opengrade check --policy ../examples/opengrade.yaml \
  --base-url http://localhost:8000 \
  --project-id <project-uuid> \
  --experiment-id <experiment-uuid>
```

Exit codes: `0` pass, `1` gate failed, `2` config error, `3` infra error. Example workflow: [`.github/workflows/release-gate.yml.example`](.github/workflows/release-gate.yml.example). Design: [`docs/superpowers/specs/2026-10-01-phase4-release-gates-design.md`](docs/superpowers/specs/2026-10-01-phase4-release-gates-design.md).

## PyPI release

Packages: **`opengrade-ai`** (SDK) and **`opengrade-ai-server`** (API + UI). Publish via tag `vX.Y.Z` and [`.github/workflows/publish.yml`](.github/workflows/publish.yml) (Trusted Publishing). Setup and checklist: [`docs/08-cli-ci.md`](docs/08-cli-ci.md#publishing-to-pypi).

## Development (backend)

```bash
cd backend
cp .env.example .env   # edit as needed
uv sync --all-extras
uv run alembic upgrade head
uv run uvicorn opengrade_server.main:app --reload --host 0.0.0.0 --port 8000
```

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

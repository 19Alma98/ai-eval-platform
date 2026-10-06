# AI Evaluation & Observability Platform

Open-source, self-hosted platform for AI quality engineering: turn production traces into datasets, run experiments, compare against a baseline, and fail CI on regressions.

**Best fit:** RAG/FAQ, classification, structured extraction, tool calling with fixed schemas, plus latency/cost/error gates.  
**Not a fit:** open-ended agents where “good” is subjective, or as a substitute for live APM. The platform measures what you define; it does not invent a quality oracle. Details: [`docs/00-project-overview.md`](docs/00-project-overview.md).

**Deployment model (v0.1):** trusted network only (localhost / private Docker network). There is **no built-in authentication**. Do not expose the stack on a public network without an external auth layer (reverse proxy, VPN, or cluster network policy).

## Quickstart

```bash
docker compose up --build
```

Frontend UI: http://localhost:3000 (included when the `web` service is up).

Check health:

```bash
curl http://localhost:8000/health
```

### Portfolio demo (People Ops assistant + Ollama)

Dataset-first RAG loop: gold test set → metrics pack → SDK-bound runs (`bind_evaluation`, `set_retrieval_documents`) → `evaluate-pack` → compare → release gate. Compares two local models (`OLLAMA_MODEL1` vs `OLLAMA_MODEL2`) on the same test set and pipeline.

1. `docker compose up --build` (API needs `CONTENT_CAPTURE_ENABLED=true`; Compose sets this)
2. Pull two chat models, e.g. `ollama pull gemma4:e2b` and `ollama pull tinyllama`
3. Sync SDK: `cd sdk && uv sync --extra openai --extra dev && cd ..`
4. Sync CLI: `cd cli && uv sync && cd ..`
5. Run: `python scripts/portfolio_demo.py`

In the UI: **Test set → Metriche → Runs**. Release policy uses pack names: `hit_at_k`, `groundedness`, `correctness`, `latency`.

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
set AIOBS_PROJECT_SLUG=demo
python main.py
```

### Instrument with Python SDK

```bash
cd sdk && uv sync --extra openai && cd ..
# see examples/sdk_hello/README.md
```

Package docs: [`sdk/README.md`](sdk/README.md).

### List / get traces

```bash
curl "http://localhost:8000/api/v1/projects/<project-uuid>/traces"
curl "http://localhost:8000/api/v1/projects/<project-uuid>/traces/<otel-trace-id-hex>"
```

## Release gate (Phase 4)

After evaluating an experiment, check a YAML policy:

```bash
cd cli && uv sync
uv run aiobs check --policy ../examples/aiobs.yaml \
  --base-url http://localhost:8000 \
  --project-id <project-uuid> \
  --experiment-id <experiment-uuid>
```

Exit codes: `0` pass, `1` gate failed, `2` config error, `3` infra error. Example workflow: [`.github/workflows/release-gate.yml.example`](.github/workflows/release-gate.yml.example). Design: [`docs/superpowers/specs/2026-10-01-phase4-release-gates-design.md`](docs/superpowers/specs/2026-10-01-phase4-release-gates-design.md).

## Documentation

Technical specification lives in [`docs/`](docs/). Phase 1 design: [`docs/superpowers/specs/2026-09-30-phase1-otlp-traces-design.md`](docs/superpowers/specs/2026-09-30-phase1-otlp-traces-design.md).

## Local CI checks

Same checks as [`.github/workflows/ci.yml`](.github/workflows/ci.yml) (ruff / mypy / pytest for backend+sdk+cli, frontend typecheck). Backend integration tests use a dedicated `aiobs_test` database on host port **5434** (created automatically; they do not wipe the Compose `aiobs` demo DB).

```bash
./scripts/ci-local.sh              # all jobs
./scripts/ci-local.sh backend      # one job
./scripts/ci-local.sh sdk cli      # subset
```

## Development (backend)

```bash
cd backend
cp .env.example .env   # edit as needed
uv sync --all-extras
uv run alembic upgrade head
uv run uvicorn aiobs.main:app --reload --host 0.0.0.0 --port 8000
```

Requires PostgreSQL. With Compose, Postgres is published on host port **5434** (`DATABASE_URL=postgresql+asyncpg://aiobs:aiobs@localhost:5434/aiobs`).

### LLM judges (LiteLLM / Ollama)

LLM judges use LiteLLM. Settings live in `backend/.env` (see `.env.example`). For local Ollama the example sets:

```bash
LLM_MODEL=ollama/gemma4:e2b
LLM_API_BASE=http://localhost:11434
```

When creating an evaluator, use `"type": "llm_judge"` and `"config": {"kind": "correctness"}` (or `answer_relevance` / `groundedness`).

# RAG FAQ portfolio example

Tiny FAQ RAG app that talks to local **Ollama**, exports OpenInference spans to the platform via OTLP, and is driven end-to-end by `scripts/portfolio_demo.py`.

## Prerequisites

1. Platform running (`docker compose up --build` from the repo root).
2. **`CONTENT_CAPTURE_ENABLED=true`** on the API (Compose `api` service sets this). Needed so `from-trace` can read Trace `input`/`output`.
3. Ollama running with a chat model:

```bash
ollama pull gemma4:e2b
# optional overrides:
# export OLLAMA_HOST=http://localhost:11434
# export OLLAMA_MODEL=gemma4:e2b
```

## Install (single backend env)

Client deps live in the backend optional extra `examples` ([`backend/pyproject.toml`](../../backend/pyproject.toml)):

```bash
cd backend
uv sync --extra examples
# or with tests/lint too:
# uv sync --all-extras
```

## Single question

```bash
cd backend
export AIOBS_PROJECT_SLUG=rag-faq
uv run --extra examples python ../examples/rag_faq/main.py "Does the platform require login?"
# broken path (no retrieval / low-quality answer):
uv run --extra examples python ../examples/rag_faq/main.py --mode broken "Does the platform require login?"
```

## Full portfolio loop

From the repo root:

```bash
cd backend && uv sync --extra examples && cd ..
cd cli && uv sync && cd ..
python scripts/portfolio_demo.py
```

(`portfolio_demo.py` invokes the RAG app via `uv run --extra examples` from `backend/`.)

This will:

1. create/reuse project `rag-faq`;
2. run all FAQ questions in `good` then `broken` mode;
3. build datasets via `from-trace`;
4. evaluate baseline vs candidate with a `quality` (`contains`) evaluator;
5. write `examples/rag_faq/aiobs.yaml`;
6. run `aiobs check` (expects exit code **1** = gate failed on the broken candidate).

Then open http://localhost:3000 and select project **RAG FAQ**.

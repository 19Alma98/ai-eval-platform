# Acme People Ops Assistant (portfolio example)

Keyword-retrieval RAG over a fictional HR/IT policy knowledge base. Calls local **Ollama** via the OpenAI-compatible API, exports OpenInference spans through the **aiobs SDK** (`bind_evaluation`, `set_retrieval_documents`), and pairs with `scripts/portfolio_demo.py` to build a `rag_qa` test set, score with the project metrics pack, and compare two models on the same exam.

## Prerequisites

1. Platform running from the repo root: `docker compose up --build`.
2. **`CONTENT_CAPTURE_ENABLED=true`** on the API (the Compose `api` service sets this). Required so bound OTLP traces populate run item outputs for scoring.
3. [Ollama](https://ollama.com/) running locally.
4. Pull **two** chat models (baseline vs candidate for the portfolio script), for example:

```bash
ollama pull gemma4:e2b
ollama pull tinyllama
```

## Environment

| Variable | Purpose |
|---|---|
| `OLLAMA_MODEL1` | Baseline model for `portfolio_demo.py` (default: `OLLAMA_MODEL` or `gemma4:e2b`) |
| `OLLAMA_MODEL2` | Candidate model for `portfolio_demo.py` (default: `tinyllama`) |
| `OLLAMA_HOST` | Ollama base URL (default: `http://localhost:11434`) |
| `OLLAMA_MODEL` | Default for single-question runs when `--model` is omitted |
| `AIOBS_PROJECT_SLUG` | Project slug for traces (default: `hr-it-assistant`) |
| `AIOBS_OTLP_ENDPOINT` | OTLP ingest URL (default: `http://localhost:8000/v1/traces`) |

Sync the SDK env once:

```bash
cd sdk && uv sync --extra openai --extra dev
```

## Single question

From the **sdk** directory (uses the SDK virtualenv; do not install the client SDK into the backend env):

```bash
cd sdk
export AIOBS_PROJECT_SLUG=hr-it-assistant
uv run --extra openai --with openai python ../examples/hr_it_assistant/main.py \
  --model gemma4:e2b "How many PTO days do full-time employees get per year?"
```

## Full portfolio loop

From the repo root (after Compose + Ollama + both models):

```bash
cd cli && uv sync && cd ..
python scripts/portfolio_demo.py
```

This creates a gold `rag_qa` test set (`expected_doc_ids` from `knowledge.json`), ensures the RAG metrics pack, runs all gold questions twice with SDK run binding (`OLLAMA_MODEL1` baseline run, then `OLLAMA_MODEL2` candidate), calls `evaluate-pack` on each run, writes `examples/hr_it_assistant/aiobs.yaml` (pack metric names), and runs `aiobs check`.

## Release gate note

Unlike a scripted “always fail” demo, **`aiobs check` may exit `0` or `1`** depending on pack scores (`hit_at_k`, judges, latency) and regression vs baseline. LLM judges require a configured judge provider in the API environment; without it, release checks may report `unavailable` for those metrics. Exit codes `2`/`3` indicate config or infra errors.

## Design

[`docs/superpowers/specs/2026-10-02-hr-it-assistant-portfolio-design.md`](../../docs/superpowers/specs/2026-10-02-hr-it-assistant-portfolio-design.md)

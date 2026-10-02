# Acme People Ops Assistant (portfolio example)

Keyword-retrieval RAG over a fictional HR/IT policy knowledge base. Calls local **Ollama** via the OpenAI-compatible API, exports OpenInference spans through the **aiobs SDK**, and pairs with `scripts/portfolio_demo.py` to compare two models on the same pipeline.

## Prerequisites

1. Platform running from the repo root: `docker compose up --build`.
2. **`CONTENT_CAPTURE_ENABLED=true`** on the API (the Compose `api` service sets this). Required so `from-trace` can read trace `input`/`output` when building datasets.
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

This runs all gold questions with `OLLAMA_MODEL1`, then `OLLAMA_MODEL2`, builds datasets and experiments, writes `examples/hr_it_assistant/aiobs.yaml`, and runs `aiobs check`.

## Release gate note

Unlike a scripted “always fail” demo, **`aiobs check` may exit `0` or `1`** depending on how well each model hits the gold `must_contain` phrases. That is expected: pick a stronger `OLLAMA_MODEL1` and a weaker `OLLAMA_MODEL2` to see regressions. Exit codes `2`/`3` indicate config or infra errors.

## Design

[`docs/superpowers/specs/2026-10-02-hr-it-assistant-portfolio-design.md`](../../docs/superpowers/specs/2026-10-02-hr-it-assistant-portfolio-design.md)

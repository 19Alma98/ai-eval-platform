# Acme People Ops Assistant (portfolio example)

Keyword-retrieval RAG over a fictional HR/IT policy knowledge base. Calls local **Ollama** via the OpenAI-compatible API, exports OpenInference spans through the **opengrade SDK** (`set_retrieval_documents`), and runs experiments with `opengrade.start_experiment` (`--eval`). `scripts/portfolio_demo.py` builds on it to score two models with the project metrics pack and compare them on the same exam.

Canonical gold lives in `knowledge.json` (full `expected_answer` + `must_contain` per question). `eval_import.csv` is a derived CSV of the same rows for API/UI import.

## Prerequisites

1. Platform running from the repo root: `docker compose up --build` (or `opengrade ui`).
2. [Ollama](https://ollama.com/) running locally.
3. Pull **two** chat models (baseline vs candidate for the portfolio script), for example:

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
| `OPENGRADE_PROJECT_SLUG` | Project for traces, created if missing (default: `hr-it-assistant`) |
| `OPENGRADE_TRACKING_URI` | Platform URL for API + OTLP (default: `http://localhost:8000`) |

Sync the SDK env once:

```bash
cd sdk && uv sync --extra openai
```

## Single question

From the **sdk** directory (uses the SDK virtualenv; do not install the client SDK into the backend env):

```bash
cd sdk
export OPENGRADE_PROJECT_SLUG=hr-it-assistant
uv run --extra openai --with openai python ../examples/hr_it_assistant/main.py \
  --model gemma4:e2b "How many PTO days do full-time employees get per year?"
```

## Experiment (`--eval`)

Runs every gold question from `knowledge.json` (or `--dataset <name|id>`) as one experiment. The SDK creates or reuses the dataset, binds each trace to its item, uploads the answers with their retrieved documents, and scores them with the project metrics pack:

```bash
cd sdk
uv run --extra openai --with openai python ../examples/hr_it_assistant/main.py \
  --eval --model gemma4:e2b --name gemma-v2 --baseline prod --concurrency 4
```

It prints the metric table and the link to the run in the UI. Use `--json` to get one result line instead. With `--app-config-id`, the system prompt comes from that App Config's snapshot.

## Full portfolio loop (model A/B)

From the repo root (after Compose + Ollama + both models):

```bash
cd backend && uv sync && cd ..
python scripts/portfolio_demo.py
```

This ensures the RAG metrics pack and runs `main.py --eval` twice on the same gold `rag_qa` test set (`expected_doc_ids` from `knowledge.json`): first `OLLAMA_MODEL1` as the baseline, then `OLLAMA_MODEL2` as the candidate with `--baseline`. It then prints the comparison, writes `examples/hr_it_assistant/opengrade.yaml` (pack metric names), and runs `opengrade check`.

## Prompt A/B loop (same model, different system prompt)

Same KB and a **single** Ollama model; the variable under test is the generation system prompt, versioned as App Config and bound to each experiment.

```bash
cd backend && uv sync && cd ..
python scripts/prompt_ab_demo.py
# optional: --skip-check
```

What it does:

1. Creates two App Config versions of `people-ops-rag` (identical `model` / `retrieval`, different `prompt.system`).
2. Runs `main.py --eval --app-config-id …` once per version on the same gold dataset. The system prompt comes from the experiment's App Config snapshot, and the candidate is compared against the baseline.
3. Prints `experiments.compare`.
4. Writes `examples/hr_it_assistant/opengrade.prompt-ab.yaml` and runs `opengrade check` (unless `--skip-check`).

In the UI, open each run’s **App config snapshot** to see the frozen prompts. Design: [`docs/superpowers/specs/2026-10-07-prompt-ab-demo-design.md`](../../docs/superpowers/specs/2026-10-07-prompt-ab-demo-design.md).

| Variable | Purpose |
|---|---|
| `OLLAMA_MODEL` | Fixed model for both runs (default: `gemma4:e2b`) |

## Quality gate note

Unlike a scripted “always fail” demo, **`opengrade check` may exit `0` or `1`** depending on pack scores (`hit_at_k`, judges, latency) and regression vs baseline. LLM judges require a configured judge provider in the API environment; without it, quality gate checks may report `unavailable` for those metrics. Exit codes `2`/`3` indicate config or infra errors.

## Design

[`docs/superpowers/specs/2026-10-02-hr-it-assistant-portfolio-design.md`](../../docs/superpowers/specs/2026-10-02-hr-it-assistant-portfolio-design.md)

# How OpenGrade works

This page connects the pieces: what runs where, the objects you work with, and the order you
use them in. Each step links to the page with the details. If you have not run OpenGrade yet,
do the [15-minute getting started](getting-started.md) first.

## The loop

```text
 trace your app ──▶ build a test set ──▶ run an experiment ──▶ compare with the baseline ──▶ CI gate
       ▲                                                                                     │
       └────────────── production traces, scores and alerts ◀────────── ship ◀───────────────┘
```

1. **Trace** your app so every request is recorded as a span tree.
2. **Build a test set** (gold questions with expected answers and documents), from a file or from production traffic.
3. **Run an experiment**: your code answers every item of the test set and the server scores the answers.
4. **Compare** the experiment with a **baseline** (the last accepted run).
5. **Gate** the pull request on a YAML policy: CI fails when quality drops.
6. **Ship and monitor**: production traces are scored, alerts fire on drift, bad answers become new test cases.

## What runs where

| Piece | Package | What it does |
|---|---|---|
| **SDK** | `opengrade-ai` (`import opengrade`) | Runs in your app and in your eval scripts: tracing, `evaluate` / `sweep`, local metrics, production scores and feedback |
| **Server + UI** | `opengrade-ai-server` (installed by `opengrade-ai[ui]`) | Stores traces, datasets and experiments; runs the server metrics and the **LLM judges**; serves the dashboard and the REST API |
| **CLI** | `opengrade` (ships with the SDK, needs the server package) | `opengrade ui` (local server), `opengrade evaluate` / `check` (CI gate), `opengrade keys` |

Two consequences that are easy to miss:

- **LLM judges run on the server**, not in your process. Their model and API key are server
  settings (`LLM_MODEL`, `LLM_API_BASE`, `LLM_API_KEY` in the `.env` next to `opengrade ui`, or in
  `backend/.env` with Docker Compose). Without a reachable judge model, traces and deterministic
  metrics still work and judge metrics show as unavailable. See
  [LLM judges](03-evaluation-engine.md#llm-judges).
- **The server is a database.** Baselines (aliases), test sets and production data live there.
  `opengrade ui` uses a SQLite file (`./opengrade.db`); for a team or CI use a persistent server
  on PostgreSQL (Docker Compose or `--backend-store-uri`). `opengrade evaluate` without a server
  URL starts a throwaway in-process server: fine for an absolute gate, but it cannot remember a
  baseline between runs.

## Objects

| Term | Meaning |
|---|---|
| **Project** | Workspace that holds everything else. `opengrade.set_project("name")` creates it on first use |
| **Trace** | Span tree of one request, sent over OTLP to `/v1/traces` |
| **Dataset** (test set) | Versioned list of items: `input`, `expected_output`, `metadata` (e.g. `expected_doc_ids`, `must_contain`, `critical`). Called *test set* in the UI |
| **Task type** | Shape of the items and default metrics: `rag_qa` (default), `classification`, `agent_tools` |
| **Metric** (evaluator) | Scores one answer, 0..1 with PASS / FAIL / SKIPPED / ERROR. Deterministic (`hit_at_k`, `must_contain`, `latency`, …), LLM judge (`groundedness`, `correctness`, …), custom judge (`LlmJudge`) or local Python (`@opengrade.metric`) |
| **Metrics set** | Named, versioned list of metrics with thresholds. Each project has a default one. Older pages and API routes call it *metrics pack* |
| **Experiment** (run) | One pass of your code over a dataset, scored by a metrics set. Records params, version and git commit |
| **Baseline / alias** | The experiment to compare with. An alias (`alias:main`) points to the last accepted run and moves on `--promote` |
| **Policy** | YAML rules (`opengrade.yaml`) that turn an experiment and its baseline into pass / fail for CI |
| **Live interaction** | A production request recorded with `init(live=True)` and scored by judges without gold. Can be promoted into a dataset |

## Step by step

### 1. Run a server

| Situation | How |
|---|---|
| Trying it out, local development | `uv add 'opengrade-ai[ui]'` and `uv run opengrade ui` (SQLite, no Docker) |
| Team, CI baselines, production traffic | `docker compose up` (PostgreSQL), or `opengrade ui --backend-store-uri postgresql+asyncpg://…` |
| Server reachable beyond localhost | set `OPENGRADE_API_KEY`, create per-client keys, put TLS in front: [Security and API keys](10-security-privacy.md) |

Apps and scripts find the server through `opengrade.set_tracking_uri(...)` or
`OPENGRADE_TRACKING_URI` (default `http://localhost:8000`), and send a key from
`OPENGRADE_API_KEY` when the server requires one.

### 2. Trace your app

```python
import opengrade

opengrade.set_tracking_uri("http://localhost:8000")
opengrade.set_project("support-bot")
opengrade.init(instrument="auto")  # OpenAI, Anthropic, LangChain, LlamaIndex, Bedrock spans


@opengrade.trace
def answer(question: str) -> str:
    docs = retriever.search(question)
    opengrade.set_retrieval_documents(docs)  # needed by retrieval metrics and RAG judges
    return llm.generate(question, docs)
```

Install the extra for your provider (`opengrade-ai[openai]`, `[anthropic]`, …, or `[ai]` for all).
Details: [Python SDK → Quickstart](../sdk/README.md#quickstart), [spans](../sdk/README.md#spans-inside-a-function-opengradespan),
[users, sessions, tags](../sdk/README.md#users-sessions-tags-and-metadata).

The same function is used in production and in experiments: write it once, evaluate it as it ships.

### 3. Build a test set

A test set is a file (CSV, JSON, JSONL), a list of dicts, a DataFrame, or a dataset already
stored on the server. One row per test case:

```jsonl
{"input": "How many PTO days do I get?", "expected_output": "20 days per year.", "expected_doc_ids": ["pto"], "category": "hr"}
{"input": "How often must passwords be rotated?", "expected_output": "Every 90 days.", "expected_doc_ids": ["security"], "must_contain": ["90 days"], "critical": true}
{"input": "What is the CEO's salary?", "answerable": false}
```

| Column | Used by |
|---|---|
| `input` (or `question`) | required: what your task receives as `item.input` |
| `expected_output` (or `expected_answer`) | reference answer: `correctness`, `context_recall` |
| `expected_doc_ids` | gold documents: `hit_at_k`, `recall_at_k`, `mrr` |
| `must_contain` | required phrases: `must_contain` |
| `answerable: false` / `expected_refusal: true` | the assistant should decline: `refusal` (no gold answer or documents needed) |
| any other column (`category`, `critical`, …) | stored in `metadata`: grouping (`group_by`, `groups`), must-pass cases (`critical`) |

With the default `task_type="rag_qa"`, every answerable row needs `expected_output` and
`expected_doc_ids`. Datasets are versioned: once a dataset has been used by an experiment,
changing it creates a new version, so old experiments stay comparable.

Grow the test set from production: a failing live interaction can be **promoted** into a dataset
with a reviewer-written answer (UI: Live page; SDK: `client.live_runs.promote`, see
[Live runs → test set](../sdk/README.md#live-runs-testset-loop)).

How many test cases? Small sets cannot detect small drops: with 20 cases the gate detects only
drops of about 0.28, with 100 about 0.07. See [statistical power](08-cli-ci.md#statistical-power-min_detectable_delta-regressionmax_detectable_delta).

### 4. Choose metrics

| You want to check | Metrics | Needs |
|---|---|---|
| The retriever finds the right documents | `hit_at_k`, `recall_at_k`, `mrr` | `expected_doc_ids`, documents from `set_retrieval_documents` |
| The answer is supported by the documents | `groundedness`, `citation_accuracy` | LLM judge, documents with text |
| The answer is right | `correctness`, `must_contain` | `expected_output` / `must_contain` |
| The answer addresses the question | `answer_relevance` | LLM judge |
| It declines when it should | `refusal` | `answerable` / `expected_refusal` |
| No personal data, toxicity or prompt injection | `pii`, `toxicity`, `prompt_injection` | LLM judge; no gold needed |
| Speed and cost | `latency`, `cost`, `token_usage` | tracing on (`opengrade.init()`) for tokens and cost |
| Exact labels, formats, tool calls | `exact_match`, `contains`, `regex`, `json_schema`, `tool_call_success` | set as a server evaluator in a metrics set |
| Something specific to your app | `@opengrade.metric` (Python) or `opengrade.LlmJudge` (criteria in plain language) | — |

All metrics, judge configuration and scoring rules: [Metrics and judges](03-evaluation-engine.md).
Writing your own: [Custom evaluators](16-custom-evaluators.md).

### 5. Run an experiment

```python
result = opengrade.evaluate(
    dataset="gold.jsonl",
    task=lambda item: answer(item.input),
    metrics=["hit_at_k", "groundedness", "correctness", "latency"],
    name="prompt-v2",
    params={"model": "gemma4", "prompt": "v2"},
)
print(result.summary(), result.url)
```

- Compare several configurations (models, prompts, `top_k`, chunk sizes) in one call with
  `opengrade.sweep(grid=...)`.
- Test only the retriever, without generating answers, with `opengrade.evaluate_retrieval`.
- Reduce LLM noise with `repeats=3`; spot a weak category with `group_by="category"`.

Details: [Python SDK → Experiments](../sdk/README.md#experiments-evaluate-start_experiment).
The experiment appears under **Experiments** in the UI, with per-item outputs, scores and judge explanations.

### 6. Compare with a baseline

Pass `baseline=` to `evaluate` (an experiment name, an id, or `alias:main`). The comparison is
paired item by item with a bootstrap confidence interval, so it tells a real regression from
noise. In the UI open the experiment and **Compare**; the CLI prints the same table.

An **alias** is how a baseline moves forward: `alias:main` points to the last run accepted on
`main`, and `--promote main` moves it when the gate passes. See
[Moving baseline](08-cli-ci.md#moving-baseline-alias-promote).

### 7. Gate the pull request

Put the experiment and the rules in one file and run it in CI:

```yaml
# opengrade.yaml
evaluate:
  task: rag_app:answer_item        # module:function taking a dataset item
  dataset: tests/gold.jsonl
  metrics: [hit_at_k, must_contain, correctness, latency]
  baseline: alias:main

hit_at_k: { min: 0.8 }
latency: { p95_max_ms: 2000 }
regression: { max_delta: -0.05, max_new_failures: 0 }
critical: { by: critical }
```

```bash
# pull request: must be compared with main
opengrade evaluate --config opengrade.yaml --require-baseline --report-md "$GITHUB_STEP_SUMMARY"
# push to main: same run, then move the baseline when it passes
opengrade evaluate --config opengrade.yaml --promote main
```

Exit code `0` passes, `1` is a failed gate, `2` a configuration error, `3` an infrastructure
error. Baselines need a persistent server (`api_base_url` in the YAML or `--base-url`) and an
`admin` API key in CI when the server is protected.

Every rule: [Policy reference](08-cli-ci.md#policy-reference). Full workflows:
[`examples/ci_regression_gate`](../examples/ci_regression_gate/README.md) (no LLM),
[`examples/llm_regression_gate`](../examples/llm_regression_gate/README.md) (real LLM and judge).

### 8. Monitor production

```python
opengrade.init(live=True, live_sample_rate=0.1, version=GIT_SHA, environment="prod")
```

- `live=True`: each top-level traced request becomes a live interaction, and a sample of them is
  scored by the gold-less judges (`groundedness`, `answer_relevance`, custom judges with `live=True`).
- `@opengrade.trace(metrics=[...])` runs your own metrics off the request path;
  `opengrade.log_score` / `opengrade.log_feedback` attach scores and thumbs up/down.
- `version` / `environment` let **Production → Health** compare one deploy with the previous one.
- Alert rules (UI or `client.alerts.create`) notify Slack or a webhook on thresholds, drift or anomalies.

Details: [Live runs](../sdk/README.md#live-runs-from-tracing-production),
[production scores and feedback](../sdk/README.md#production-scores-and-feedback), [alerts](../sdk/README.md#alerts).
What the server stores (prompts, answers, document text) and how to turn it off: [content capture](10-security-privacy.md#content-capture-and-redaction).

### 9. Close the loop

Review failing live interactions (UI: **Live**, filter *Failing*), write the correct answer, and
promote them into the test set. The next pull request is gated on them too.

## Where to go next

- Runnable, offline walkthrough of steps 2–8: [`examples/sdk_tour`](../examples/sdk_tour/README.md)
- Every SDK function: [Python SDK](../sdk/README.md) and the [API reference](reference/index.md)
- Every CLI flag and policy rule: [CLI and CI](08-cli-ci.md)

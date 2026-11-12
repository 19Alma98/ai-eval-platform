# OpenGrade

**Unit tests for your LLM app.** Trace it, score it on a test set, and fail the pull request
when answer quality drops — self-hosted, one package, no SaaS.

[![Documentation](https://img.shields.io/badge/docs-latest-blue)](https://opengrade-docs.vercel.app/)
[![CI](https://github.com/19Alma98/ai-eval-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/19Alma98/ai-eval-platform/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/opengrade-ai)](https://pypi.org/project/opengrade-ai/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

![OpenGrade walkthrough: overview, traces, experiments, baseline compare, quality gate, production judge](docs/images/hero.gif)

## The problem

You change a prompt, swap the model or tweak the retriever. The demo still looks fine. A week
later users notice that the assistant now invents answers it used to get right.

Normal tests can't catch this: the output is text, and "correct" is a judgement. OpenGrade turns
that judgement into numbers you can compare between two versions of your app, and into an exit
code your CI understands.

## What it looks like

A pull request breaks the retriever. Every absolute threshold still passes — but OpenGrade
compares the PR with the last accepted run on `main`, question by question, and blocks it:

```text
Test cases worse than baseline (4):
  ▼ How do I book business travel?
      hit_at_k: 1.000 PASS → 0.000 FAIL
      baseline:  Business travel must be booked through Navan at least 14 days in advance.
      candidate: Payroll is processed on the last business day of each month.
  ...
│ hit_at_k.min                     │ 0.8   │ 0.8    │ passed │
│ regression.hit_at_k.mean_score   │ -0.20 │ -0.05  │ failed │
│ regression.hit_at_k.new_failures │ 4     │ 0      │ failed │
Result: FAILED          ← exit code 1, the PR is red
```

Run it yourself in 30 seconds, offline: [`examples/ci_regression_gate`](examples/ci_regression_gate/README.md).

## How it works

```text
 trace your app ──▶ test set ──▶ experiment ──▶ compare with main ──▶ CI gate
       ▲                                                                │
       └──────── production traces, scores, alerts ◀──── ship ◀─────────┘
```

**1. Trace** — a decorator and two lines. OpenAI, Anthropic, LangChain, LlamaIndex and Bedrock
calls become spans automatically.

```python
from opengrade import Opengrade

og = Opengrade(project="support-bot")

@og.trace
def answer(question: str) -> str:
    docs = retriever.search(question)
    og.set_retrieval_documents(docs)   # feeds the retrieval metrics and the RAG judges
    return llm.generate(question, docs)
```

**2. Evaluate** on a test set, against the version on `main`:

```python
result = og.evaluate(
    dataset="gold.jsonl",
    task=lambda item: answer(item.input),
    metrics=["hit_at_k", "groundedness", "correctness"],
    baseline="alias:main",
)
print(result.summary())
```

**3. Gate** the pull request with a YAML policy:

```yaml
# opengrade.yaml
evaluate: { task: rag_app:task, dataset: gold.jsonl, metrics: [hit_at_k, groundedness], baseline: alias:main }
groundedness: { min: 0.8 }
regression: { max_delta: -0.05, max_new_failures: 0 }
```

```bash
opengrade evaluate --config opengrade.yaml --require-baseline   # exit 1 when quality drops
```

**4. Watch production** with the same metrics, user feedback and alerts:
`og.init_tracing(live=True, live_sample_rate=0.1)`.

## What you can measure

| | Metrics | Needs an LLM |
|---|---|---|
| **Retrieval** | `hit_at_k`, `recall_at_k`, `precision_at_k`, `mrr`, `ndcg` | no |
| **Answers** | `groundedness`, `correctness`, `answer_relevance`, `citation_accuracy`, `refusal` | yes (judge) |
| **Context** | `context_precision`, `context_recall` | yes |
| **Multi-turn chat** | `conversation_consistency`, `query_rewrite_faithfulness`, `resolution` | yes |
| **Safety** | `pii`, `toxicity`, `prompt_injection` | yes |
| **Deterministic** | `exact_match`, `must_contain`, `regex`, `json_schema`, `latency`, `cost`, `tool_call_success` | no |
| **Your own** | `@opengrade.metric` (Python) or `LlmJudge("tone", criteria="…")` | your choice |

`groundedness`, `correctness` and the context judges break the text into individual claims and
check each one, so a failing score comes with the exact sentence that is unsupported and the
document it was checked against.
They run on any model [LiteLLM](https://docs.litellm.ai/docs/providers) supports, including a
local Ollama.

## Quickstart

Python ≥ 3.12 and [`uv`](https://docs.astral.sh/uv/).

Try the dashboard without installing anything:

```bash
uvx --from 'opengrade-ai[ui]' opengrade ui   # http://127.0.0.1:8000, data in ./opengrade.db
```

Add it to your project:

```bash
uv add 'opengrade-ai[ui]'
uv run opengrade ui
```

No Docker, no database server. (`pip install 'opengrade-ai[ui]'` works too.) For the LLM judges, add a `.env` next to it:

```bash
LLM_MODEL=openai/gpt-4o-mini       # or ollama/gemma4:e2b with LLM_API_BASE=http://localhost:11434
LLM_API_KEY=...
```

Then follow **[Getting started (15 min)](docs/getting-started.md)**, or run the
**[SDK tour](examples/sdk_tour/README.md)**: six offline scripts covering tracing, RAG
verification, model comparison, production monitoring, prompt A/B and multi-turn chat.

## Is it a fit?

**Yes**, if your answers can be checked against something: RAG and Q&A assistants,
classification, extraction, tool calls with a fixed schema.

**No**, if "good" is purely subjective (open-ended creative agents), or if you need a general
APM. OpenGrade measures what you define; it doesn't invent a quality oracle.

**Compared with** observability platforms such as Langfuse or Arize Phoenix, OpenGrade is built
around the **pre-release gate**: paired statistical comparison with a baseline, per-question
diffs and a CI exit code. Compared with metric libraries such as Ragas or DeepEval, it adds
tracing, storage, a UI and production monitoring around the metrics.

## Learn more

| | |
|---|---|
| [How OpenGrade works](docs/workflow.md) | the end-to-end workflow and its concepts |
| [Python SDK](sdk/README.md) | tracing, experiments, metrics, production API |
| [CLI and CI](docs/08-cli-ci.md) | `opengrade evaluate`, policy reference, GitHub Actions |
| [Metrics and judges](docs/03-evaluation-engine.md) | how each metric and judge scores |
| [Custom evaluators](docs/16-custom-evaluators.md) | Python metrics and custom LLM judges |
| [Security](docs/10-security-privacy.md) | API keys, content capture, trust model |
| [Changelog](CHANGELOG.md) | what changed in each release |

## Run it for a team

API, UI and PostgreSQL in containers (image on GHCR, runs as non-root):

```bash
cp backend/.env.example backend/.env   # judges, API key, all settings with defaults
docker compose pull && docker compose up   # http://localhost:8000
```

Before exposing it beyond localhost, set `OPENGRADE_API_KEY` and put TLS in front:
see [Security](docs/10-security-privacy.md).

## Development

The repository holds the SDK (`sdk/`), the API server (`backend/`) and the Next.js UI (`frontend/`).

```bash
python scripts/package_ui.py                        # build the UI into the server package
cd backend && uv sync --all-extras && uv run opengrade ui
cd sdk && uv sync && uv run pytest
```

## License

[Apache-2.0](LICENSE)

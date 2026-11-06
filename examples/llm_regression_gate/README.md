# LLM regression gate: "the PR must not be worse than `main`" with a real LLM

Same CI contract as [`ci_regression_gate`](../ci_regression_gate/README.md) — PR compared
to the last accepted `main` run, promote only on push to `main` — but for a RAG pipeline
whose answers change from run to run (sampling LLM) and whose quality is partly scored by
an LLM judge.

Without `repeats` and a paired bootstrap, two runs of the same code look like a regression. Without a pinned judge, a model upgrade shifts every score and can trip the gate even when the app did not change.

Needs [Ollama](https://ollama.com) locally (or any OpenAI-compatible endpoint). No OpenGrade server.

## Try it locally (~5–15 min)

```bash
ollama pull gemma4:e2b
./examples/llm_regression_gate/run_demo.sh
```

Needs [`uv`](https://docs.astral.sh/uv/). The demo pulls `opengrade-ai[ui,openai]` from PyPI on first run (`uvx`).

## What `run_demo.sh` does

The script clears a local SQLite store, then runs three `opengrade evaluate` steps. Each
step prints the CLI summary and checks the exit code.

| Step | Simulates | Bug | Result |
|------|-----------|-----|--------|
| 1 | push to `main` | — | PASS + `--promote main` |
| 2 | PR, same code, new LLM samples | — | PASS: noise is not a regression |
| 3 | PR drops the retrieved context | `RAG_PROMPT=no_context` | **FAIL**: critical + groundedness |

Step 2 is the point of this example: with a sampling LLM two runs of the same code never
give the same answers. `repeats` + the paired bootstrap keep that from failing CI.

### Step 1 — push to `main` (bootstrap)

```bash
opengrade evaluate --config opengrade.yaml --version main-1 --promote main
```

Runs the 24-question gold set three times (`repeats: 3`) on the healthy pipeline
(retriever + context in the prompt). There is no baseline yet, so only the absolute floors
(`hit_at_k.min`, `must_contain.min`, judge `min`s, `critical`) apply. `--promote main`
stores the experiment as alias `main` in `ci.db`. Exit 0.

### Step 2 — PR, unchanged code, new samples

```bash
opengrade evaluate --config opengrade.yaml --version pr-1 --require-baseline
```

Same code, new LLM draws. Compared against `alias:main`. Individual answers differ, but
the paired bootstrap does not see a proven drop, and `critical` still passes. Exit 0.

If this step fails on your machine, look at which check failed: a judge floor (`min`) too
close to the model's real score, or a gold set too small (`min_detectable_delta`).

### Step 3 — PR that drops the retrieved context

```bash
RAG_PROMPT=no_context opengrade evaluate --config opengrade.yaml \
  --version pr-2 --require-baseline
```

`RAG_PROMPT=no_context` stops passing retrieved documents to the model, so it answers from
memory. Groundedness drops; security questions marked `"critical": true` fail. Exit **1**.

Broken answers show up in the CLI under "Test cases worse than baseline".

## What gets traced

In this example tracing is enough for the metrics and judges to see what the model saw; it is not a full `retrieve → generate`
span tree. For that pattern see [`sdk_tour/nimbus_apps/rag.py`](../sdk_tour/nimbus_apps/rag.py).

With `evaluate.init: true`, the CLI calls `opengrade.init(..., instrument="auto")`. For each gold-set item (and each `repeat`), `opengrade.evaluate` opens **one root `CHAIN` span**. What lands on that tree:

| Source | What you see | Role |
|--------|--------------|------|
| `evaluate` root span | `input.value` (question), `output.value` (answer) | One request = one span |
| `opengrade.set_retrieval_documents(docs)` in [`rag_app.py`](rag_app.py) | Docs attached to the **current** (root) span | Feeds `hit_at_k`, groundedness, etc. — **not** a separate `RETRIEVER` span |
| OpenAI client → Ollama | Child **LLM** span (prompt, tokens) | Only if `openinference-instrumentation-openai` is installed (`run_demo.sh` adds it with `--with`) |

Typical tree:

```text
opengrade.eval rag-llm-ci          ← question + answer + retrieved docs
  └─ chat.completions              ← auto-instrumented LLM call
```

Traces are stored in the embedded API behind `ci.db`. Point `--base-url` at a shared
OpenGrade server to browse them in Production → Traces.

## What [`opengrade.yaml`](opengrade.yaml) adds for an LLM

| Problem | Setting |
|---------|---------|
| LLM noise looks like a regression | `repeats: 3` |
| Judge changes shift every score | judge pinned, `temperature: 0` |
| A security answer breaks while averages hold | `critical` (`"critical": true` in the gold set) |
| One question breaks, another improves | `regression.max_new_failures` |
| Gold set too small to see a drop | power warning, `max_detectable_delta` |
| "Not proven worse" is not "as good" | `non_inferiority_margin` ([example](../non_inferiority_gate/README.md)) |

## How to use this

In CI, wire it up exactly like [`ci_regression_gate`](../ci_regression_gate/README.md):
`--require-baseline` on pull requests, `--promote main` on push to `main`.

Copy [`github-workflow.yml.example`](github-workflow.yml.example) and switch
`evaluate.judge` to a cloud model first (drop `api_base`, set `api_key_env`).

More: [`docs/08-cli-ci.md`](../../docs/08-cli-ci.md).

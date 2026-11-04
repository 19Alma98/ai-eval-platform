# OpenGrade SDK tour

A small, runnable `uv` project that shows how an AI engineer uses the OpenGrade Python SDK to **trace, test, compare, monitor and A/B prompts** of LLM applications. Each script covers one use case, prints what it is doing step by step, and is commented so you can copy the patterns into your own code.

You play the AI engineer of **Nimbus**, a fictional cloud file-storage company with two AI
applications:

| App | What it does | Code |
|---|---|---|
| Support assistant (RAG) | answers customer questions from 13 help-center articles: retrieve → generate | [`nimbus_apps/rag.py`](nimbus_apps/rag.py) |
| Ticket classifier (not RAG) | routes support tickets to billing / technical / account / sales, after a PII guardrail | [`nimbus_apps/classifier.py`](nimbus_apps/classifier.py) |

**Everything runs offline.** The default models `fake-small` and `fake-large` are deterministic stand-ins (no GPU, no API key), so the results below are reproducible. Swap in a real model (Ollama, OpenAI…) with one environment variable when you are ready, see [Real models and LLM judges](#real-models-and-llm-judges).

## The five use cases

| # | Question you have | Script | SDK features | Where to look in the UI |
|---|---|---|---|---|
| 1 | *Does everything run fine? What happened in this request?* | [`01_tracing.py`](01_tracing.py) | `@opengrade.trace`, `opengrade.span`, `set_user` / `set_session` / `set_tags` / `set_metadata`, `using_attributes`, `set_error` | Production → Traces |
| 2 | *Does my RAG give the right answers?* | [`02_verify_rag.py`](02_verify_rag.py) | gold dataset, `evaluate_retrieval`, `evaluate`, built-in + custom metrics, baseline, quality gate | Datasets, Experiments |
| 3 | *Which architecture / model is best?* | [`03_compare_architectures.py`](03_compare_architectures.py) | `sweep` (grid of configurations), leaderboard, baseline comparison | Experiments → Compare |
| 4 | *How do I monitor it live with metrics made for my product?* | [`04_custom_metrics_and_monitoring.py`](04_custom_metrics_and_monitoring.py) | `@opengrade.metric`, `@trace(metrics=...)`, `log_score`, `log_feedback`, `LlmJudge`, alerts as code | Production → Health, Live, Alerts |
| 5 | *Which system prompt is better (same model)?* | [`05_prompt_ab.py`](05_prompt_ab.py) | App Config versions, `app_config_id` on `start_experiment`, snapshot on the run, `experiments.compare` | Experiments → App config snapshot |

Run them in this order: each one builds on the previous (you trace the app, then you test it, then you compare versions of it, then you watch it in production, then you A/B the prompt).

## Setup

**1. Start the OpenGrade platform** (API + UI on http://localhost:8000) in another terminal, in any directory (it creates `./opengrade.db` there):

```bash
uvx --from 'opengrade-ai[ui]' opengrade ui
```

or `docker compose up --build` at the root of this repository. To run the platform from the sources of this repository, see [getting started](../../docs/getting-started.md). No LLM judge is needed: everything the tour scores by default is deterministic.

**2. Install the tour** (from this directory):

```bash
cd examples/sdk_tour
uv sync
```

`pyproject.toml` points `opengrade-ai` at the SDK in this repository (`[tool.uv.sources]`).
In your own project you would simply run `uv add opengrade-ai`.

**3. Optional settings:** `cp .env.example .env` and edit. The defaults work with a local platform on port 8000.

**4. Run the scripts:**

```bash
uv run python 01_tracing.py
uv run python 02_verify_rag.py
uv run python 03_compare_architectures.py
uv run python 04_custom_metrics_and_monitoring.py
uv run python 05_prompt_ab.py
```

Everything lands in the project **nimbus-support** (created on the first run).

## Project layout

```text
sdk_tour/
├── 01_tracing.py                       use case 1: traces and spans
├── 02_verify_rag.py                    use case 2: gold set, metrics, quality gate
├── 03_compare_architectures.py         use case 3: sweeps and leaderboards
├── 04_custom_metrics_and_monitoring.py use case 4: production metrics, feedback, alerts
├── 05_prompt_ab.py                     use case 5: App Config prompt A/B
├── nimbus_apps/                        "your" code: the apps under test
│   ├── rag.py           RAG pipeline + its tracing (read this one first)
│   ├── retrieval.py     knowledge base, keyword and BM25 retrievers (no OpenGrade code)
│   ├── llm.py           real OpenAI-compatible client or offline fake models
│   ├── classifier.py    ticket classifier with a GUARDRAIL span
│   ├── quality.py       custom metrics shared by tests and production
│   ├── datasets.py      registers the gold sets on the platform
│   └── settings.py      environment variables (.env)
├── data/
│   ├── knowledge_base.json   13 help-center articles
│   ├── gold_rag.jsonl        18 questions with reference answer, gold documents, facts
│   └── gold_tickets.jsonl    16 tickets with the expected queue
└── tests/test_apps.py   offline unit tests of the apps and metrics (uv run pytest)
```

---

## 1. Tracing: see what your applications do

**Question:** a customer says the assistant gave a strange answer. What did it retrieve?
Which model answered? How long did each step take? Did it fail?

A **trace** is the record of one request. It is made of **spans**, one per step, each with
input, output, duration, status and attributes. Instrumenting the RAG takes a decorator,
two `with` blocks and one call (simplified from [`nimbus_apps/rag.py`](nimbus_apps/rag.py)):

```python
@opengrade.trace(name="support_assistant")  # 1 call = 1 trace
def answer_question(question: str, config: RagConfig = DEFAULT_CONFIG) -> str:
    with opengrade.span("retrieve", kind="RETRIEVER", input=question):  # one step
        docs = search(question, strategy=config.retriever, top_k=config.top_k)
        opengrade.set_retrieval_documents(docs)  # what the model saw → metrics, judges
    with opengrade.span("generate", kind="CHAIN", input=question):
        return generate_answer(question, docs, model=config.model, system=PROMPTS[config.prompt])
```

and once at startup:

```python
opengrade.set_tracking_uri("http://localhost:8000")
opengrade.set_project("nimbus-support")
opengrade.init(service_name="nimbus-support", instrument="auto", version="1.4.0", environment="dev")
```

`instrument="auto"` makes calls to OpenAI, Anthropic, LangChain, LlamaIndex or Bedrock
appear as LLM spans with prompt, tokens and cost, with no extra code. For a provider
without an instrumentor, open the `LLM` span yourself: see `_fake_llm_call` in
[`nimbus_apps/llm.py`](nimbus_apps/llm.py).

The script then adds what makes traces useful in day-to-day work:

| Step | Pattern | Why |
|---|---|---|
| 2 | `set_user`, `set_session`, `set_tags`, `set_metadata` inside the request handler | Filter the trace list by customer (`user:u-bob`), conversation (`session:conv-1`), plan (`tag:plan-free`, `plan:pro`) |
| 3 | `using_attributes(tags=[...], metadata={...})` around a block | Same context for every span of a batch job or a middleware, without touching each function. Also: a non-RAG app with `GUARDRAIL` and `TOOL` spans |
| 4 | an exception inside a span / `set_error("...")` | Failures are marked ERROR (red), count in the error rate and can trigger alerts. A handled problem (fallback answer) can be flagged without raising |

**In the UI:** Production → Traces. Open a `support_assistant` trace for the
`retrieve → generate → llm.chat` tree, filter `session:conv-1` for a whole conversation,
`tag:nightly-batch` for the batch job, and note the two red traces from step 4.

> Tracing never breaks your app: if the platform is down, spans are dropped with one
> warning and your code runs as usual.

---

## 2. Verify the RAG answers against a gold set

**Question:** before shipping a change, is the assistant still answering correctly?

Traces tell you *what happened*; to know whether it was *right* you need expected results.
The gold set [`data/gold_rag.jsonl`](data/gold_rag.jsonl) has one row per question:

```json
{"input": "How long is the password reset link valid?",
 "expected_output": "The password reset link is valid for 1 hour.",
 "metadata": {"expected_doc_ids": ["password-reset"], "must_contain": ["1 hour"],
              "category": "security", "answerable": true}}
```

| Field | Used by |
|---|---|
| `expected_doc_ids` | retrieval metrics `hit_at_k`, `recall_at_k`, `mrr` |
| `must_contain` | `must_contain`: the facts the answer has to state |
| `expected_output` | LLM judges such as `correctness` (optional) |
| `category` | `group_by="category"`: scores per category |
| `answerable` | the custom metric `refusal_is_correct` |

The script goes through five steps:

1. **Register the gold set** as `nimbus-rag-gold-v1` ([`nimbus_apps/datasets.py`](nimbus_apps/datasets.py)).
   When you change the questions, bump the version: runs are only comparable on the same set.
2. **Test the retriever alone** with `opengrade.evaluate_retrieval`: no LLM call, so it is
   cheap enough to run on every change to chunking or embeddings.
3. **Test the whole pipeline** with `opengrade.evaluate`:

   ```python
   result = opengrade.evaluate(
       dataset="nimbus-rag-gold-v1",
       task=lambda item: answer_question(item.input),  # your app, unchanged
       metrics=[
           "hit_at_k",
           "must_contain",
           "latency",  # built-in
           cites_retrieved_source,
           refusal_is_correct,
           answer_is_concise,
       ],  # yours
       baseline="alias:rag-main",  # compare with the accepted version
       group_by="category",
   )
   print(result.summary())
   ```

   Custom metrics are plain functions ([`nimbus_apps/quality.py`](nimbus_apps/quality.py)):

   ```python
   @opengrade.metric(threshold=1.0, version=1, requires=("output", "documents"))
   def cites_retrieved_source(s: opengrade.Sample) -> opengrade.Score:
       cited = set(re.findall(r"\[([\w-]+)\]", s.output))
       retrieved = {d["id"] for d in s.documents}
       ...
       return opengrade.Score(1.0, explanation=f"cites {sorted(cited)}")
   ```

4. **Read the failures** item by item (`print_failures`): question, answer, expected answer
   and the reason given by each failing metric. With the default model you will see a
   multi-document question answered only halfway and an *over-refusal*: the assistant says
   "I don't know" although the docs cover the topic.
5. **Quality gate:** minimum scores per metric. When the gate passes, the run becomes the
   `rag-main` baseline (`client.experiments.set_alias`); the script exits `1` when it fails.

**Try it:** run it once (gate passes, baseline set), then with a worse model:

```bash
TOUR_MODEL=fake-small uv run python 02_verify_rag.py
```

```text
  metric                  mean   pass_rate  vs baseline
  must_contain            0.444  0.444      -0.333 regression
  ...
  FAIL  must_contain              0.44  (min 0.75)
  -> gate failed: 'rag-main' is not moved
```

The "vs baseline" column is a paired statistical comparison on the same questions, so a
real regression is told apart from noise. For CI (PR checks, Markdown/JUnit reports) use
the `opengrade evaluate` command: see [`examples/ci_regression_gate`](../ci_regression_gate/README.md).

---

## 3. Compare architectures and models

**Question:** keyword search or BM25? How many documents? Which model? Is the new classifier
really better?

`opengrade.sweep` runs one experiment per configuration on the same gold set and ranks them.
Your task receives the configuration as a second argument:

```python
def full_pipeline(item, params):
    return answer_question(item.input, DEFAULT_CONFIG.with_params(params))


result = opengrade.sweep(
    dataset="nimbus-rag-gold-v1",
    task=full_pipeline,
    grid={"model": ["fake-small", "fake-large"], "retriever": ["keyword", "bm25"]},
    params={"top_k": 3, "prompt": "v2"},  # fixed, stored with every run
    metrics=["hit_at_k", "must_contain", cites_retrieved_source, refusal_is_correct],
)
print(result.summary("must_contain"))  # leaderboard, best first
best = result.best("must_contain")
fastest = result.best("opengrade.latency_p95_ms")  # latency: lower is better
```

The script runs three comparisons:

1. **Retrieval architectures** (`retriever=` instead of `task=`): retriever × top_k, scored
   with hit@k, recall@k and MRR. `top_k=1` cannot find both documents of the two-document
   questions, and BM25 ranks the right document first more often than keyword search.
2. **Full pipeline**: model × retriever, answer quality next to latency p95. Here the model
   matters much more than the retriever, which is exactly the kind of insight a sweep gives you.
3. **Not only RAG**: ticket classifier `rules-v1` vs `rules-v2` with the built-in
   `exact_match` metric, v2 compared with v1 as its baseline (`+0.375 improved`).

```text
Sweep rag-architecture: 4 configurations, ranked by must_contain (higher is better)
  #  configuration                        must_contain  hit_at_k  ...  opengrade.latency_p95_ms
  1  model=fake-large, retriever=keyword  0.778         1.000          43
  2  model=fake-large, retriever=bm25     0.778         1.000          49
  3  model=fake-small, retriever=bm25     0.444         1.000          11
  4  model=fake-small, retriever=keyword  0.389         1.000          13
```

**In the UI:** open the Compare link printed at the end: all configurations side by side,
filtered on the `sweep` parameter, with any two metrics plotted against each other.
`pandas.DataFrame(result.to_records())` gives you the same table in a notebook.

---

## 4. Custom metrics and production monitoring

**Question:** once live, how do I know the assistant keeps working, with metrics that mean
something for *my* product?

In production there is no expected answer, but you can still measure a lot on real traffic:

| What | How | Example in the script |
|---|---|---|
| Your Python metrics, on every call or a sample | `@opengrade.trace(metrics=[...], metrics_sample_rate=...)` | `cites_retrieved_source`, `answer_is_concise` (the **same** functions used in the tests of script 2) and `retrieval_confidence` (production only) |
| Values your code already knows | `opengrade.log_score(name, value)` | `resolved_by_assistant`: answered, or handed over to a human? |
| What users think | `opengrade.log_feedback(positive, trace_id=...)` | thumbs up / down from the chat widget |
| A quality an LLM has to judge | `opengrade.LlmJudge("support_tone", criteria="...", live=True)` | only with `TOUR_LLM_JUDGES=1` |
| Alerts on any of the above | `client.alerts.create(...)` | fail rate of a score, error rate, latency anomaly |

```python
opengrade.init(service_name="nimbus-support", environment="prod", version="1.4.0", live=True)


@opengrade.trace(name="assistant", metrics=PRODUCTION_METRICS, metrics_sample_rate=1.0)
def assistant(question: str) -> str:
    return answer_question(question)  # metrics run after return, in the background


@opengrade.trace(name="support_chat")
def support_chat(question, *, user_id, conversation_id) -> dict:
    ...
    answer = assistant(question)
    opengrade.log_score("resolved_by_assistant", not is_refusal(answer))
    return {"answer": answer, "trace_id": opengrade.current_trace_id()}


# later, when the user clicks a thumb in the UI of your product:
opengrade.log_feedback(False, trace_id=trace_id, user_id="u-03", comment="I needed a real answer")
```

The script sends 14 simulated chat messages, then lists the answers that need attention,
with the reason (a score below threshold or a thumbs-down):

```text
  ! Who is the CEO of Nimbus?
      resolved_by_assistant = 0.0  (no answer in the docs: ticket opened)
      retrieval_confidence = 0.1505  (top retrieval score 1.2)
      user_feedback = 0.0  (I needed a real answer)
```

Finally it creates five alert rules **as code**, idempotently (safe to run at every deploy).
With this traffic, *Too many hand-offs to humans* (4 out of 14 > 20%) fires within a minute.
Set `TOUR_ALERT_WEBHOOK_URL` to a Slack incoming webhook to receive it.

**In the UI:** Production → Health (error rate, latency, cost, scores; filter `prod` and the
version), Production → Live → Failing, Production → Alerts.

> The loop closes here: a bad production answer, reviewed and given a reference answer, is
> promoted into the gold set (`client.live_runs.promote`), and script 2 tests it on every
> change from then on.

---

## Real models and LLM judges

**Real models.** Any model name that does not start with `fake-` is called through an
OpenAI-compatible API, and traced automatically by the OpenInference instrumentor:

```bash
uv sync --extra llm                      # openai + openinference-instrumentation-openai
ollama pull gemma4:e2b
TOUR_MODEL=gemma4:e2b uv run python 02_verify_rag.py
TOUR_COMPARE_MODELS=gemma4:e2b,llama3.2 uv run python 03_compare_architectures.py
```

For OpenAI set `LLM_BASE_URL=https://api.openai.com/v1`, `LLM_API_KEY=sk-...` and
`TOUR_MODEL=gpt-4o-mini`. With real (non-deterministic) models, consider `repeats=3` in
`evaluate` / `sweep` so that noise is not taken for a difference.

**LLM judges.** Deterministic metrics check facts and documents; LLM judges check what only
a reader can (is every claim supported by the documents? does the answer match the
reference?). Configure a judge model on the platform (`LLM_MODEL`, `LLM_API_KEY` in
`backend/.env`, see the root README), then set `TOUR_LLM_JUDGES=1`: script 2 adds
`groundedness`, `correctness`, `answer_relevance` and `citation_accuracy`, script 3 adds
`groundedness` and `correctness` to the sweep, and script 4 registers the custom
`support_tone` judge and lets the platform judges grade live traffic.

## Apply it to your own application

1. **Trace** the entry point with `@opengrade.trace`, each stage with `opengrade.span`, and
   call `opengrade.set_retrieval_documents(docs)` where your retriever returns. Add user,
   session and tags in your request handler.
2. **Write a gold set:** 20–50 real questions with gold document ids and the facts the answer
   must contain. Start from production traces you have reviewed.
3. **Write two or three metrics** for what "good" means in your product (citations, format,
   length, refusals, a business rule) with `@opengrade.metric`.
4. **Run `evaluate`** on every change, keep a baseline alias, and gate on it in CI.
5. **Use `sweep`** whenever you are choosing between options (model, prompt, top_k, chunking).
6. **Version prompts as App Configs** and bind experiments with `app_config_id` (script 5)
   so compares keep a frozen snapshot of what ran.
7. **In production:** `init(live=True, environment="prod", version=...)`, the same metrics on
   `@trace(metrics=...)`, `log_feedback` from your UI, and alerts on what you cannot afford
   to miss.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `OpenGrade is not reachable at http://localhost:8000` | Start the platform (step 1 of the setup) or set `OPENGRADE_TRACKING_URI` |
| `Real models need the 'llm' extra` | `uv sync --extra llm`, or keep a `fake-*` model |
| Connection refused on `:11434` | Ollama is not running (`ollama serve`), or set `LLM_BASE_URL` |
| LLM judge metrics show `ERROR` / unavailable | No judge model on the platform: leave `TOUR_LLM_JUDGES=0` or configure one |
| Script 2 exits with code 1 | The quality gate failed: that is the point of the gate. Read step 4 of its output |
| Alerts stay `no_data` | Rules look at the last 60 minutes of `prod` traffic with at least 5 samples: run script 4 again |

## 5. Prompt A/B through versioned App Configs

**Question:** same model and retriever — is the new system prompt better?

Script [`05_prompt_ab.py`](05_prompt_ab.py) creates two versions of the App Config family
`nimbus-support-rag` (identical `model` / `retrieval`, different `prompt.system`), runs
one experiment per version with `app_config_id`, and compares them. The task reads
`prompt.system` from the experiment snapshot (`exp.params`), so the prompt under test is
the versioned one — not an ad-hoc string in the script.

```bash
uv run python 05_prompt_ab.py
TOUR_MODEL=gemma4:e2b uv run python 05_prompt_ab.py   # real model: quality delta shows up
```

**In the UI:** open each run’s **App config snapshot** to see the frozen prompts side by
side with the scores.

## Next steps

- [`examples/ci_regression_gate`](../ci_regression_gate/README.md): the gate of script 2 in
  GitHub Actions, with statistical regression checks.
- [`examples/llm_regression_gate`](../llm_regression_gate/README.md): the same with a real
  model and an LLM judge.
- [SDK reference](../../sdk/README.md) for every function used here.

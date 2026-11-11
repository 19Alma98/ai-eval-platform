# opengrade

Python SDK for **OpenGrade**: OTLP/HTTP export with optional OpenInference instrumentation, plus a control-plane `Client` for datasets, experiments, and evaluation.

## Install

```bash
uv add opengrade-ai
uv add 'opengrade-ai[openai]'
uv add 'opengrade-ai[ui]'   # also installs opengrade-ai-server (API + packaged UI)
```

Pip remains supported:

```bash
pip install opengrade-ai
pip install 'opengrade-ai[openai]'
pip install 'opengrade-ai[ai]'   # all tier-1 OpenInference instrumentors
pip install 'opengrade-ai[ui]'  # also installs opengrade-ai-server (API + packaged UI)
```

Individual extras: `openai`, `anthropic`, `langchain`, `llama-index`, `bedrock`, `ui`.

Import path remains `import opengrade`. Local platform (SQLite + UI):

```bash
uv add 'opengrade-ai[ui]'
uv run opengrade ui   # http://127.0.0.1:8000 — creates ./opengrade.db
```

The `opengrade` command ships with the SDK. Without the `[ui]` extra it exits with a hint to install it.

Develop from this monorepo:

```bash
cd sdk && uv sync
uv sync --extra openai   # add OpenAI instrumentor
# UI packaging (server wheel): python scripts/package_ui.py
# then: cd backend && uv sync --all-extras && uv run opengrade ui
```

## Quickstart

Two lines and a decorator. Provider calls (OpenAI, Anthropic, LangChain, …) become child spans when the matching instrumentor extra is installed:

```python
from openai import OpenAI
from opengrade import Opengrade

og = Opengrade(project="demo")  # created if missing; platform at OPENGRADE_TRACKING_URI

client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")


@og.trace
def ask(q: str) -> str:
    r = client.chat.completions.create(
        model="gemma4:e2b",
        messages=[{"role": "user", "content": q}],
    )
    return r.choices[0].message.content or ""


ask("ping")
```

- **`Opengrade(project="demo")`** names the project; it is found or created on the platform in the background, before the first export. The platform URL defaults to `http://localhost:8000` (`tracking_uri=` or `OPENGRADE_TRACKING_URI`). Use `project_id=` / `project_slug=` instead to point at a project that must already exist (nothing is created; a wrong one is reported with a warning).
- **`@og.trace`** starts tracing on the first call with the defaults of `og.init_tracing()` (`instrument="auto"`). Call `og.init_tracing(...)` yourself, before the first traced call, only to pass options: `live=True`, `version=`, `environment=`, sampling, `instrument=False`.
- **No `flush()` needed** in a script: pending spans are flushed at interpreter exit. Call `og.flush()` when you want to wait for delivery (tests, serverless handlers).
- **Everything is on `og`**: `og.trace`, `og.span`, `og.set_user`, `og.set_retrieval_documents`, `og.log_score`, `og.evaluate`, … The module-level `opengrade.trace` / `opengrade.span` / `opengrade.set_*` still exist: they act on whichever instance is active (`with og.activate():`), which is what a function shared by [several projects in one process](#multiple-projects-in-one-process-opengrade) needs.

Runnable examples: [`examples/sdk_hello/`](https://github.com/19Alma98/ai-eval-platform/blob/main/examples/sdk_hello/README.md) (Ollama via OpenAI-compatible API) and the guided [`examples/sdk_tour/`](https://github.com/19Alma98/ai-eval-platform/blob/main/examples/sdk_tour/README.md) (tracing, RAG verification, architecture comparison, production metrics and alerts; runs offline).

### Multiple projects in one process (`Opengrade`)

One `Opengrade` per project or tenant. Each keeps its own settings, clients and OTLP route on the shared `TracerProvider`:

```python
from opengrade import Opengrade

acme = Opengrade(project="acme", service_name="worker-acme")
contoso = Opengrade(project="contoso", service_name="worker-contoso")


@acme.trace
def acme_job(payload: dict) -> str: ...      # always traced into "acme"


acme.client.datasets.list()                   # control plane of "acme"
contoso.evaluate(dataset=rows, task=task)     # experiment in "contoso"
```

When **the same function serves several projects** (multi-tenant API), decorate it with the module-level `@opengrade.trace` and pick the instance per request:

```python
import opengrade


@opengrade.trace
def answer(question: str) -> str: ...


with tenant_og.activate():   # routes this call (and what it calls) to tenant_og
    answer(question)
```

- **`@og.trace` / `og.span`** always go to `og`, whatever is activated around them. A child span joins its parent's instance, so a trace is never split across projects.
- **`@opengrade.trace` / `opengrade.span`** go to the instance activated with `with og.activate():` (`opengrade.current()`). With a single traced instance in the process they need no activation at all.
- **Explicit `Client(..., project_id=...)`** pins the control plane to one project regardless of `current()` — use this in libraries and long-lived clients.
- **Worker threads** do not inherit `ContextVar` values from the parent thread. `@og.trace` is unaffected. For module-level `@opengrade.trace` with several instances, wrap thread entry points with `contextvars.copy_context().run(...)` (or call `activate()` inside the thread); otherwise spans started there are not exported (nothing is guessed, nothing raises).
- **Tracing never breaks your code:** without an active instance `@opengrade.trace` / `opengrade.span` run the function untraced, and an internal tracing failure is logged once, never raised.

Runnable multi-tenant FastAPI sample: [`examples/fastapi_multi_tenant/`](https://github.com/19Alma98/ai-eval-platform/blob/main/examples/fastapi_multi_tenant/README.md).

#### Testing with `Opengrade` and `httpx2.MockTransport`

Isolate SDK state in pytest without a live platform: construct `Opengrade` with `Settings`, inject a `Client` that uses `httpx2.MockTransport`, and scope calls with `activate()`. Helpers: `tests.support.instance.make_og` / `init_og` / `activated`, and `tests.support.reset.reset_sdk`.

```python
import httpx2
import opengrade
from opengrade import Opengrade, Settings


def test_two_projects(mock_handler):
    cap_a: list[httpx2.Request] = []
    a = Opengrade(settings=Settings(tracking_uri="http://a", project_id="proj-a"))
    a._runtime.client = opengrade.Client(
        "http://a",
        transport=httpx2.MockTransport(mock_handler(cap_a)),
        project_id="proj-a",
    )
    with a.activate():
        a.client.projects.list()
    assert cap_a and "proj-a" in cap_a[0].url.path
```

See `sdk/tests/test_opengrade.py` and `sdk/tests/test_client.py` for full handlers. Running the suite in parallel (`pytest-xdist`) is optional; tests call `reset_sdk()` where needed.

### API summary

| API | Purpose |
|---|---|
| `Opengrade(project="my-app", ...)` | Runtime handle: settings, shared clients, tracing, evaluate. Any `Settings` field is a keyword; the rest comes from `OPENGRADE_*` |
| `Settings(tracking_uri=..., project=..., project_id=..., project_slug=..., ...)` | Immutable config (`Opengrade(settings=...)`); `Settings.from_env()` merges env vars. `project` is a name, created if missing; `project_id` / `project_slug` must exist |
| `og.init_tracing(...)` | Optional: tracing options (`live`, `version`, `environment`, sampling, `instrument="auto"` \| list \| `False`). Without it, tracing starts with the defaults on the first `og.trace` / `og.span` |
| `with og.activate():` / `opengrade.current()` | Route module-level `opengrade.trace` / `opengrade.span` to this instance (functions shared by several projects) |
| `og.set_project(name)` / `await og.aset_project(name)` | Get-or-create project; updates bound `project_id` on shared clients |
| `og.get_project()` | Active project or `None` |
| `og.client` / `og.async_client()` | Shared control-plane clients for this instance |
| `og.flush()` | Drain spans (and related queues) for this instance |
| `og.evaluate(...)` / `og.start_experiment(...)` / `og.sweep(...)` | Experiments (activate the instance for the call) |
| `og.log_score` / `og.log_feedback` / `og.score_trace` | Production scores tied to the active runtime |
| `@og.trace` | Parent CHAIN span (sync/async/generators); optional input/output capture (32 KiB cap) |
| `with og.span(name, kind=...)` | Child span for a block of code (`with` / `async with`): retrieve, rerank, tool call… |
| `og.set_user` / `set_session` / `set_tags` / `set_metadata` | User, session, tags and key/value metadata of the current trace (filterable in the UI) |
| `og.using_attributes(...)` | Same attributes for every span opened in a block (e.g. in a request middleware) |
| `og.set_input` / `set_output` | Override OpenInference I/O on the current span (no OTEL import) |
| `og.set_attribute` / `set_attributes` | Custom attributes on the current span |
| `og.set_error(...)` | Mark current span ERROR |
| `og.current_trace_id()` | 32-char hex trace id while inside a `@trace` span |
| `opengrade.bind_evaluation(...)` | Bind current span to `experiment_id` + `dataset_item_id` |
| `og.set_retrieval_documents(docs)` | Attach retrieval docs for RAG eval context: dicts or objects with an `id` (and `text` / `content` / `page_content`, `score`, `title`, `metadata`). A document without an id is skipped with a warning, never an exception |
| `og.evaluate_retrieval(...)` | Score only the retriever (hit@k, recall@k, MRR, optional context judges), no answer generated |
| `opengrade.Client(...)` | Control-plane REST client (projects, datasets, experiments, …) |
| `opengrade.AsyncClient(...)` | Async control-plane client (projects, live_runs, trace_scores, health) |

App code should use these helpers instead of importing OpenTelemetry directly.

### Spans inside a function (`og.span`)

`@og.trace` covers a whole function; `og.span` traces one block inside it, so each stage
of a pipeline shows up as its own step in the trace timeline:

```python
@og.trace
def answer(question: str) -> str:
    with og.span("retrieve", kind="RETRIEVER", input=question) as s:
        docs = retriever.search(question)
        s.set_output([d.id for d in docs])
    with og.span("rerank", kind="RERANKER", attributes={"rerank.top_k": 3}) as s:
        docs = reranker.rank(question, docs)[:3]
        s.set_output([d.id for d in docs])
    og.set_retrieval_documents(docs)  # still feeds retrieval metrics / judges
    return generate(question, docs)
```

- `kind` is an OpenInference span kind: `CHAIN` (default), `LLM`, `RETRIEVER`, `RERANKER`, `EMBEDDING`,
  `TOOL`, `AGENT`, `GUARDRAIL`, `EVALUATOR`, `PROMPT` (case-insensitive; other values are sent as-is
  with a warning).
- The handle has `set_input`, `set_output`, `set_attribute(s)`, `set_error`, `trace_id`, `span_id`.
  `set_output` on a span does not change the experiment output (use `og.set_output` for that).
- An exception in the block marks the span ERROR and propagates. `async with` works the same way.
- Outside any traced call, the span is a root span; with `init_tracing(live=True)` it becomes a live
  interaction like an outermost `@og.trace` (`live=False` opts out).

### Users, sessions, tags and metadata

```python
@og.trace
def answer(question: str, user, chat_id: str) -> str:
    og.set_user(user.id)
    og.set_session(chat_id)  # all turns of a conversation share it
    og.set_tags("beta", "rerank-v2")  # accumulates across calls
    og.set_metadata(tenant=user.tenant, prompt_version="v3")
    ...


# Or for every span opened in a block (blocks nest; tags and metadata accumulate):
with og.using_attributes(user_id=user.id, session_id=chat_id, tags=["beta"]):
    answer(question)
```

- They use the OpenInference keys `user.id`, `session.id`, `tag.tags` and `metadata` (JSON), so any
  span of the trace works and auto-instrumented spans inside `using_attributes` get them too (when
  `openinference-instrumentation` is installed).
- The setters act on the current span and are no-ops outside a traced call.
- Metadata values should be scalars (others are stored as JSON text); keys starting with `_` are
  reserved. Limits: 50 tags, 50 metadata keys, 500 chars per value.
- In the UI (Production → Traces) filter with `tag:beta`, `tenant:acme`, `user:…` or `session:…`;
  click a tag, user, session or metadata value on a trace to see all matching traces. API:
  `GET /projects/{id}/traces?tag=beta&metadata=tenant:acme&user_id=…&session_id=…` (repeat `tag` /
  `metadata`; all must match), `GET /projects/{id}/traces/facets` for the values seen.

## Experiments (`evaluate` / `start_experiment`)

One call runs a task over a dataset, writes the outputs, scores them and compares against a baseline. Examples use an `Opengrade` handle `og` (from the quickstart); `og.evaluate()` and `og.start_experiment()` call `activate()` for you:

```python
import opengrade
from opengrade import Opengrade, Settings

og = Opengrade(settings=Settings(project_slug="demo"))
og.set_project("demo")
og.init_tracing()  # optional: adds trace context (tokens, cost, tool calls) to each item


def answer_question(item):  # item.input, item.expected_output, item.metadata
    docs = retrieve(item.input)
    og.set_retrieval_documents(docs)  # feeds hit_at_k / recall_at_k / groundedness
    return generate(item.input, docs)


def short(item, output) -> bool:  # local metric: float | bool | None
    return len(output) < 400


result = og.evaluate(
    dataset="gold-v1",  # name/id, path, list/iterable of dicts, pandas/Polars DataFrame
    task=answer_question,
    metrics=["groundedness", "hit_at_k", short],
    # metrics_set_id="…",  # reuse an existing set (e.g. from_experiment in the CLI); XOR with metrics kinds
    name="gemma-prompt-v2",
    params={"model": "gemma4"},  # stored as the experiment's model_config
    baseline="prod",  # experiment name (latest), id, or "alias:main" (promoted baseline)
    # version="v1.4.0",  # default: short git SHA of the code under test
    # git=False,  # the commit/branch/dirty state is recorded automatically; False skips it
    max_concurrency=8,
    # repeats=3,  # run each item 3 times: per-item mean, flaky items counted
    # group_by="category",  # also report means / baseline deltas per metadata value
)
print(result.summary(), result.url)

# Promote the run as the new baseline (the CLI does this with --promote when the gate passes):
og.client.experiments.set_alias("main", result.id, note="accepted")
```

Manual loop, same plumbing (binding, flush, output upload, scoring on exit):

```python
with og.start_experiment("v2", dataset="gold-v1", metrics=["hit_at_k"]) as exp:
    for item in exp.items():
        with exp.run(item) as run:  # root span bound to (experiment, item)
            run.log(my_app(item.input))  # or og.set_output(...) anywhere inside
print(exp.result.summary())
```

How it behaves:

- **Metrics**: a string is a server metric kind (`hit_at_k`, `recall_at_k`, `mrr`, `must_contain`, `groundedness`, `correctness`, `answer_relevance`, `context_precision`, `context_recall`, `citation_accuracy`, `refusal`, `latency`). A dict sets threshold/config, for example `{"kind": "hit_at_k", "config": {"k": 3}}`. The SDK finds or creates a metrics set that holds exactly those kinds, using the project's defaults for anything you leave out. `metrics=None` uses the project default set. A Python metric runs locally (see *Custom metrics* below), and its scores are submitted to the platform (`POST /experiments/{id}/client-results`). From there they are aggregated, shown in the UI and compared with the baseline like server metrics.
- **Datasets**: pass a registered name/id, a path to CSV/JSON/JSONL, a list or iterable of dicts, a pandas DataFrame, or a Polars DataFrame. Rows need an `input` column (or `question`). `expected_output` (or `expected_answer`), `context` and `metadata` map to item fields; any other column goes into `metadata` (so `expected_doc_ids` and `must_contain` work). `task_type` is inferred from inline rows when you do not pass it: `rag_chat` for chat-shaped inputs, `rag_qa` when rows carry `expected_doc_ids`, otherwise `generic` (plain input → output, nothing else required). In a `rag_qa` set every row needs `expected_output` and `expected_doc_ids`, except rows labelled unanswerable (`metadata.answerable: false` or `expected_refusal: true`), which may omit both. A missing `input`/`question` raises `opengrade.DatasetColumnError` (CSV headers are checked up front). Inline rows are hashed into a dataset name, so re-running on the same rows reuses the same dataset. Generators are materialised before upload (no lazy streaming).
- **Outputs** are uploaded with `PUT /experiments/{id}/outputs`, so this works without `init_tracing()`. With tracing on, `finish()` waits for the OTLP traces to be bound (up to 30s) and merges their context in. Your explicit output always wins.
- **Repeats**: `repeats=N` runs the task N times per item (each run is its own trace and output, `repeat` 0..N-1). Scores are averaged per item before aggregating, so every item weighs once and the baseline comparison still pairs items; the bootstrap CI then reflects run-to-run noise less. Items whose PASS/FAIL changes between repeats count as flaky (`result.flaky`, the `flaky` column in `summary()`, the UI scorecard). In a manual loop pass `exp.run(item, repeat=i)`. Max 100.
- **Concurrency:** `max_concurrency > 1` runs items on a thread pool. Caller
  ContextVars (for example `using_attributes(...)` and `activate()`) are copied
  into each worker. Threads *you* start still need `copy_context().run(...)` or
  `activate()` inside the thread — see multi-tenant notes above.
- **Groups**: `group_by="category"` (a dataset-item metadata key, dotted paths allowed) adds per-group means and baseline deltas: `result.groups` and a `by category:` block in `summary()`. A drop on one kind of question shows up even when the overall mean holds. `client.experiments.summary(id, group_by=...)` / `compare(..., group_by=...)` return the same data; the release gate can enforce it with a `groups` policy block (see [CLI and CI](https://github.com/19Alma98/ai-eval-platform/blob/main/docs/08-cli-ci.md#gate-per-group-groups)).
- **Errors**: when a task raises, `evaluate` records it on the item (`result.errors`, `metadata.error`) and moves on. Pass `raise_on_error=True` to stop instead. When the `with` block raises, nothing is scored. Bad dataset columns raise `DatasetColumnError` before the run starts.

### Citations and refusals

Two server judges check behaviours that answer-quality scores miss:

```python
og.evaluate(
    dataset=[
        {
            "input": "How many PTO days?",
            "expected_output": "20 days.",
            "metadata": {"expected_doc_ids": ["pto"]},
        },
        # unanswerable from the knowledge base: the assistant should decline. No gold
        # documents and no reference answer needed (retrieval metrics skip the item).
        {"input": "What is the CEO's salary?", "metadata": {"answerable": False}},
    ],
    task=answer_question,  # answers like "You get 20 days [pto]."
    metrics=["citation_accuracy", "refusal"],
)
```

- `citation_accuracy`: parses the answer's citation markers (`[pto]`, `[1]`, `[1, 3]`, `[^2]`; another style via `{"kind": "citation_accuracy", "config": {"pattern": r"\(source: ([^)]+)\)"}}`) and checks that every cited source was actually retrieved and supports the sentence that cites it. Score = supported cited sentences / cited sentences; an answer citing nothing fails (`require_citations: false` to skip instead), `min_coverage: 0.8` also fails answers where too few sentences carry a citation. Documents come from `set_retrieval_documents` / retriever spans and need an `id`.
- `refusal`: did the assistant decline exactly when it should? Mark items with `metadata.answerable` (or `expected_refusal`), or give a reference answer that declines ("The documents do not say"). Without either (e.g. on live traffic) the judge reads the retrieved documents. `metadata.outcome` is `correct_answer`, `correct_refusal`, `over_refusal` or `missed_refusal`. `{"kind": "refusal", "config": {"method": "phrases"}}` matches refusal phrases (English/Italian, or your own `refusal_phrases`) without an LLM call.

Both run on live traffic too (enable them in the project's metrics set; they ship disabled).

### Conversations (multi-turn RAG)

When the unit under test is a chat, each test case is the history plus the last user question; the reference answer and gold documents are those of the last turn:

```python
import opengrade

rows = [
    {
        "input": {
            "history": [
                {"role": "user", "content": "Do you have a Pro plan?"},
                {"role": "assistant", "content": "Yes, we offer a Pro plan."},
            ],
            "question": "How much does it cost?",
        },
        "expected_output": "The Pro plan costs 8 dollars per user per month.",
        "expected_doc_ids": ["plans"],
        "must_contain": ["8 dollars"],
    },
]


@og.trace
def chat(history: list[dict], question: str) -> str:
    query = rewrite(history, question)  # "How much does the Pro plan cost?"
    og.set_search_query(query)          # what you searched for → query_rewrite_faithfulness
    docs = retriever.search(query)
    og.set_retrieval_documents(docs)
    return llm.generate(history, question, docs)


def task(item):
    turn = opengrade.chat_input(item)  # .history (list of turns), .question
    return chat([t.model_dump() for t in turn.history], turn.question)


result = og.evaluate(
    dataset=rows,  # chat-shaped inputs → task_type "rag_chat"
    task=task,
    metrics=[
        "hit_at_k", "must_contain",                 # deterministic, last turn
        "groundedness",                             # judges that score the last turn
        "query_rewrite_faithfulness",               # is the search query faithful to the conversation?
        "conversation_consistency",                 # does the answer contradict earlier turns?
        "resolution",                               # was the user's need resolved?
    ],
)
```

- The judges need a judge model on the server (`LLM_MODEL`); without one they are reported as "could not run", not as a score of 0. `hit_at_k`, `recall_at_k`, `mrr` and `must_contain` need none.
- In production, call `og.set_session(conversation_id)` in the traced handler: Production → Conversations groups the turns into a timeline, runs the session judges and lets you promote a conversation to a `rag_chat` test case.

### Custom metrics

```python
@opengrade.metric(threshold=0.5, version=2, requires=("documents",))
def cites_source(s: opengrade.Sample) -> opengrade.Score:
    hit = any(d["id"] in s.output for d in s.documents)
    return opengrade.Score(1.0 if hit else 0.0, explanation="cited" if hit else "no citation")


og.evaluate(dataset="gold-v1", task=answer_question, metrics=["hit_at_k", cites_source])
```

- `Sample` fields: `input`, `output`, `expected` (dataset `expected_output`), `documents` (from `set_retrieval_documents`), `context`, `metadata`, `trace_id`, `item_id`.
- Return `opengrade.Score(value, label=, explanation=, metadata=)`, a float, a bool, `None` or `{"score": ...}`. The explanation shows per item in the UI; `metadata` (JSON-serializable, no NaN/inf) is stored with the result. A non-finite score is an ERROR.
- `label` can only fail, skip or error an item (`"FAIL"`, `"SKIPPED"`, `"ERROR"`): PASS/FAIL otherwise comes from the threshold, so `label="PASS"` does not make a score below the threshold pass.
- To change the threshold or name of an existing metric, wrap it again: `opengrade.LocalMetric(cites_source, threshold=0.8)` keeps its function, `requires` and config.
- `fn(item, output)` (two parameters) still works and receives the dataset item. `async def` metrics work too.
- `requires`: `Sample` fields that must be non-empty (`output`, `expected`, `documents`, `context`). When one is missing the item is SKIPPED, not failed.
- `version` is stored in the metric config: bump it when the code changes, so compare reports a config mismatch instead of a misleading delta.
- When the task fails on an item, that item counts as FAIL (score 0). When the metric raises, the item is ERROR. A local metric name must not match a server evaluator name (409). If the submission fails, `result.metrics` falls back to the in-process mean.

### Custom LLM judges

When "good" is a quality an LLM has to judge (tone, format, policy, completeness), describe it in plain language instead of writing a prompt and a parser. The server runs the judge, so its scores are stored, shown in the UI, compared with the baseline and gated by the release check like built-in metrics.

```python
tone = opengrade.LlmJudge(
    "tone",
    criteria="The answer is polite and professional, uses no slang and never blames the user.",
    scale="binary",  # or "1-5" (score 0, .25, .5, .75, 1)
    fields=("input", "output"),  # + "expected", "documents", "metadata"
    threshold=0.5,
    # levels={5: "warm and formal", 1: "rude"}, examples=[{"output": "yo", "verdict": "fail"}],
    # model="gpt-4o-mini",  # default: the server's LLM_MODEL
)

print(
    tone.preview(input="Can I carry over PTO?", output="lol no").explanation
)  # try it, nothing stored
og.evaluate(dataset="gold-v1", task=answer_question, metrics=["groundedness", tone])
```

- The judge is stored as a project evaluator (`custom_judge`); `evaluate` reuses it while the config is unchanged and creates a new version when it changes, so different criteria are never compared as the same metric.
- `live=True` also scores production traffic from `init_tracing(live=True)`, next to the built-in judges (a live judge cannot read `expected`). `evaluate` registers the judge; for production only, call `tone.register()` once (e.g. at startup). You can then alert on its `score_fail_rate` / `score_mean`.
- Missing inputs (no answer, no reference for `expected`, no documents for `documents`) SKIP the item. Judge failures are ERROR with the reason.
- UI: Metrics → **Custom judges** (with a "Grade sample" preview), and "Add a custom judge" on a metrics set.

### Params and run metrics
```python
with og.start_experiment("v2", dataset="gold-v1", params={"model": "gemma4"}) as exp:
    exp.log_params(temperature=0.2)  # merged into the experiment's model_config
    exp.run_task(answer_question)
    og.log_metrics({"cost_usd": total_cost})  # experiment-level scalar, last value wins
print(exp.result.experiment_metrics)
```

- `log_params` merges into `model_config` until an evaluation starts. After that, or when the experiment was created from an app config, the server answers 409: start a new experiment instead.
- `log_metrics` stores one final number per key (no steps). Keys use letters, digits and `_ . - /`. They appear in `result.summary()` with the delta against the baseline, and can gate a release via the release-check policy: `{"experiment_metrics": {"cost_usd": {"max": 2.0}}}`.
- `og.log_params` / `og.log_metrics` act on the active experiment: inside `with og.start_experiment(...)` and inside any item run (`exp.run(...)`, `run_task`, `evaluate()` tasks). Elsewhere they raise `RuntimeError`. With concurrency > 1, call `log_metrics`/`log_params` once outside per-item code: per-item calls overwrite each other (last write wins).
- Every `finish()` logs `opengrade.error_rate`, `opengrade.latency_p50_ms` and `opengrade.latency_p95_ms` (the task's wall-clock latency as measured by the SDK, over the items that did not fail, nearest-rank percentiles).

### Comparing configurations (`sweep`)

Run the same test set over a grid of configurations and rank them in one call:

```python
def answer(item, params):  # each configuration's params come in as the second argument
    docs = retrieve(item.input, top_k=params["top_k"])
    og.set_retrieval_documents(docs)
    return generate(item.input, docs, model=params["model"])


result = og.sweep(
    dataset="gold-v1",
    task=answer,
    grid={"model": ["gemma4", "llama3.3"], "top_k": [3, 5]},  # 4 experiments
    # variants=[{"model": "gemma4", "top_k": 3}, ...],         # or an explicit list
    metrics=["groundedness", "hit_at_k", "correctness"],
    params={"prompt": "v3"},  # stored on every experiment
    baseline="alias:main",  # optional: each configuration is compared with it
)
print(result.summary())  # leaderboard, best first, with latency p95 and error rate
best = result.best("correctness")  # SweepRun: .params, .result (ExperimentResult)
rows = result.to_records()  # list of dicts → pandas.DataFrame(rows)
print(result.url)  # Compare view pinned to the sweep's experiments
```

- Every configuration is a normal experiment named `<sweep> [model=gemma4, top_k=3]`, with its configuration plus `sweep=<name>` stored as params. In the UI (**Experiments → Compare all**) filter on the `sweep` parameter, color the charts by any parameter, and plot quality against cost or latency.
- `leaderboard(metric)` / `best(metric)` rank on a scored metric or a run metric (`opengrade.latency_p95_ms`, `cost_usd` from `log_metrics`); latency, cost, error and token metrics rank lower-is-better (override with `lower_is_better=`).
- The test set is resolved (inline rows uploaded) once. Configurations run one after another; `max_concurrency` and `repeats` apply within each. A configuration that fails to run is reported in `result.errors` and the others still run (`raise_on_error=True` stops instead).
- `retriever=` instead of `task=` sweeps a retrieval-only evaluation (see below), e.g. chunk sizes or embedding models: `og.sweep(dataset=..., retriever=search, grid={"chunk_size": [256, 512]}, k=5)`.

### Retrieval-only evaluation (`evaluate_retrieval`)

Score the retrieval step without generating answers: cheap enough to run on every change to chunking, embeddings or reranking.

```python
def search(query: str):  # or search(item); return the ranked documents
    return vector_store.similarity_search(query, k=10)


result = og.evaluate_retrieval(dataset="gold-v1", retriever=search, k=5)
print(result.summary())  # hit_at_k, recall_at_k, mrr at cutoff 5 + retrieval latency
```

- The retriever gets the dataset item, or the question text when its first parameter is named `query`, `question`, `text` or `q`. Sync or async.
- Documents can be dicts (`id`, `text`, …), strings, LangChain `Document` (`id` / `metadata["id"|"doc_id"|"source"]`) or LlamaIndex `NodeWithScore` (node id). Pass `doc_id=lambda doc: ...` to choose the id. Gold ids come from the item's `expected_doc_ids`; documents without an id get a text hash, which never matches them.
- Default metrics: `hit_at_k`, `recall_at_k`, `mrr` with cutoff `k` (deterministic, no LLM). Add `"context_precision"` / `"context_recall"` to have the LLM judge rate relevance and coverage against `expected_output`. Metrics that grade an answer (`groundedness`, `correctness`, …) are rejected.
- The experiment is stored with `params["eval_mode"] = "retrieval"`; `opengrade.latency_p50_ms` / `_p95_ms` measure the retriever alone.

## Control plane (`Client`)

HTTP client for the platform JSON API (uses `httpx2`, a core SDK dependency). Without `base_url` it uses the tracking URI. In app code prefer `og.client` on your `Opengrade` handle over building a `Client()` per function:

```python
from opengrade import Opengrade, Settings

og = Opengrade(settings=Settings(tracking_uri="http://localhost:8000", project_slug="demo"))
og.set_project("demo")
client = og.client
datasets = client.datasets.list()  # project_id defaults to the active project
exp = client.experiments.create(name="baseline", dataset_id=datasets[0].id)
```

Project-scoped methods (`datasets.create/list/create_with_items`, `experiments.create/list`, `metrics_packs.ensure/get`, `live_runs.submit/list`, `projects.get`) take `project_id` as an optional first argument: explicit value > active `Settings.project_id` / `set_project()` > `OPENGRADE_PROJECT_ID` > lazy slug resolve (`Settings(project_slug=…)` / `OPENGRADE_PROJECT_SLUG`), else `ValueError`.

Explicit, self-managed client:

```python
from opengrade import Client

with Client("http://localhost:8000") as client:
    project = client.projects.create(name="Demo", slug="demo")
    ds = client.datasets.create_with_items(
        project.id,
        name="gold-v1",
        task_type="rag_qa",
        items=[{"input": "Q?", "expected_output": "A"}],
    )
    # or CSV/JSONL via multipart import:
    # client.datasets.import_items(ds.id, path="gold.csv", format="csv")

    exp = client.experiments.create(
        project.id,
        name="baseline",
        dataset_id=ds.id,
        model_config={"model": "gemma4:e2b"},
    )
    client.metrics_packs.ensure(project.id)
    # after OTLP-bound runs:
    client.experiments.evaluate_pack(exp.id)
    summary = client.experiments.summary(exp.id)
```

Control-plane methods return **Pydantic** models (see `opengrade.models`); use attributes or `.model_dump()` for a dict. Prefer `with Client(...)` / `client.close()` so the shared `httpx2` connection pool is released.

Namespaces: `projects`, `datasets` (`create`, `create_with_items`, `add_item`, `get`, `list`, `import_items`), `experiments` (`create`, `get`, `list_outputs`, `upsert_outputs`, `evaluate_pack`, `summary`, `compare`), `metrics_packs` (`ensure`, `get`), `metrics_sets` (`list`, `get`, `create`), `evaluators` (`list`, `create`, `preview`), `alerts`, `live_runs` (`submit`, `list`, `get`, `promote`, `rescore`), `app_configs` (`create_app_config`, `list_app_configs`, `set_alias`, `get_aliases`). Non-2xx responses raise `OpengradeAPIError` (with parsed FastAPI `detail` when present).

### Async control plane (`AsyncClient`)

For FastAPI / async RAG apps, use `AsyncClient` so control-plane calls do not block the event loop. Prefer `og.async_client()` and `await og.aset_project(...)`. MVP surface: `health`, `projects`, `live_runs` (full), `trace_scores`. Datasets, experiments, metrics packs/sets, and app configs remain on the sync `Client`.

```python
import opengrade
from opengrade import Opengrade, Settings

og = Opengrade(settings=Settings(tracking_uri="http://localhost:8000", project_slug="my-rag"))


# FastAPI lifespan
async def lifespan(app):
    await og.aset_project("my-rag")
    og.init_tracing(instrument=False)
    yield
    await og.async_client().aclose()


@og.trace(name="answer")
async def answer(q: str) -> str:
    text = "..."
    client = og.async_client()
    await client.live_runs.submit(question=q, answer=text, documents=[])
    return text
```

Or manage the client yourself: `async with AsyncClient(...) as client: ...`. Update `og`'s `Settings` (or construct a new `Opengrade`) to change tracking URI; if an event loop is already running, `aclose` the async client before replacing settings (otherwise the shared async client is dropped with a warning).

### Releases and environments

Tag production traffic with the release and deployment that served it, so a deploy can be compared with the previous one:

```python
og.init_tracing(
    version=os.environ["GIT_SHA"], environment="prod"
)  # or OPENGRADE_VERSION / OPENGRADE_ENVIRONMENT
```

They become the OTel resource attributes `service.version` / `deployment.environment` (when opengrade attaches to a host TracerProvider, they are stamped on each span as `opengrade.version` / `opengrade.environment`). Production → Health then filters by environment and version and shows a **By version** table (error rate, latency, cost per trace, failing scores side by side); the Traces list filters the same way, and alert rules can be scoped to an `environment` / `version`. API: `GET /projects/{id}/monitoring?environment=&version=`, `/monitoring/versions`, `/monitoring/facets`, `GET /projects/{id}/traces?environment=&version=`.

### Trace sampling and capture size

```python
og.init_tracing(
    project_slug="acme",
    trace_sample_rate=0.1,  # or OPENGRADE_TRACE_SAMPLE_RATE
    max_capture_bytes=16_384,  # or OPENGRADE_MAX_CAPTURE_BYTES
)
```

- `trace_sample_rate` is OTEL head sampling (`TraceIdRatioBased`) when opengrade creates the `TracerProvider`. It does not change a host provider's sampler.
- `max_capture_bytes` caps UTF-8 size of input/output values written on `@og.trace` spans (default 32 KiB).

#### Capture redaction

Use `og.configure_capture(redact=..., redact_output=...)` for instance-wide scrubbing, or `@og.trace(redact=..., redact_output=...)` to override (or inherit with `None`) per function. Automatic capture writes `input.value` as a flat JSON object of bound parameter names → values (`self` / `cls` omitted); values are truncated to the capture budget after redaction. See [Content capture and redaction](../docs/10-security-privacy.md#content-capture-and-redaction) in the security guide.

For **generator** and **async-generator** functions, `@og.trace` joins streamed chunks into `output.value` (plain strings and common LLM delta shapes by default). Pass `join_chunks=(chunk, acc) -> ...` to accumulate differently (`acc` starts as `None`). The span is current only during each `next()` / `__anext__`; between yields it is not the active trace context. Abandoned iterators finish the span on `close()` / `aclose()`.

### Live runs from tracing (production)

With `live=True`, the outermost `@og.trace` call outside an experiment becomes a live interaction at OTLP ingestion; no separate `live_runs.submit` call is needed.

```python
og.init_tracing(
    project_slug="acme", live=True, live_sample_rate=0.1
)  # or OPENGRADE_LIVE=1, OPENGRADE_LIVE_SAMPLE_RATE=0.1


@og.trace
def answer(question: str) -> str:
    docs = retrieve(question)  # documents from RETRIEVER spans or set_retrieval_documents()
    return llm(question, docs)
```

- Every call is recorded; only `live_sample_rate` of them (default `1.0`) are sent to the judge. The rest show `judge_status="unsampled"` and can still be judged with `live_runs.rescore`. Sampling is deterministic on the trace id.
- Question = the only string argument (or a `question`/`query`/`input`/`prompt` kwarg); answer = the return value. Override with `og.set_input(...)` / `og.set_output(...)`.
- `@og.trace(live=False)` excludes a function; `live=True` opts one in when `init_tracing(live=...)` is off.
- The server stores span text by default; with `CONTENT_CAPTURE_ENABLED=false` input/output are redacted and no live interaction is created.
- Idempotent per trace (`external_id="trace:<trace_id>"`).

### Production scores and feedback

Attach scores and end-user feedback to a production trace. They are stored per trace and show up on the Live page (next to the judge verdicts), in the "Failing" filter and on the overview.

```python
og.init_tracing(live=True)


@opengrade.metric(threshold=0.5, requires=("documents",))
def cites_source(s: opengrade.Sample) -> float:
    return float(any(d["id"] in s.output for d in s.documents))


@og.trace(
    metrics=[cites_source], metrics_sample_rate=0.2
)  # 20% of traces, scored off the request path
def answer(question: str) -> str:
    docs = retrieve(question)
    og.set_retrieval_documents(docs)
    return generate(question, docs)


@og.trace
def handle(question: str) -> dict:
    out = answer(question)
    opengrade.current().log_score("answer_chars", len(out))  # current trace
    return {"answer": out, "trace_id": og.current_trace_id()}  # send the id to your frontend


# later, from the thumbs button (trace_id is the one handle() returned)
og.log_feedback(True, trace_id=trace_id, user_id="user-42", comment="great")
```

- `og.log_score(name, value, *, trace_id=None, label=None, explanation=None, threshold=None, metadata=None)` (or `current().log_score` inside an active instance): without `trace_id` it uses the current trace. PASS/FAIL follows the same rule as experiment metrics: a `FAIL` label fails; a value under `threshold` fails; otherwise, with a threshold a value at or above it passes, and without one only a value of 0 fails.
- `og.log_feedback(positive, *, trace_id=None, comment=None, user_id=None)`: stored as `user_feedback` (1 or 0); `positive` must be a bool (or 0/1). One value per user per trace: a user changing their mind replaces it. Without `user_id` the feedback is anonymous and all anonymous feedback on a trace shares one row (last write wins). A thumbs-down counts as a failure in the Live "Failing" filter.
- `og.score_trace(metric, sample, trace_id=...)` runs one metric now, on the calling thread (only the sending is in the background), and stores the result. The trace is `trace_id`, else `sample.trace_id`, else the current trace. A raising metric queues `label="ERROR"` with the exception as explanation (returns `True` when that score is queued); missing `requires` skips with `False`.
- `@og.trace(metrics=[...], metrics_sample_rate=1.0)` runs your metrics after the function returns successfully (not when it raises, not inside experiments, which score their own metrics). Sampling is per trace and configured separately from the judge's `live_sample_rate`; both use the same hash of the trace id, so when both are set the sampled traces are nested (the lower rate's traces are a subset of the higher rate's).
  - `Sample.input` is what you passed to `og.set_input()` inside the call, else the only argument, else `{"args", "kwargs"}`; `Sample.output` is what you passed to `og.set_output()` inside the call, else the return value (so a handler can return a response object and still have its metrics see the answer); `Sample.documents` is the last `set_retrieval_documents()` inside the call (including nested `@og.trace` helpers on the same thread); `expected` is `None`, so metrics with `requires=("expected",)` are skipped. Input, output and documents are deep-copied when the job is queued (so later mutation is invisible); samples over 256 KiB serialized are skipped with a warning. Capture uses a ContextVar: a worker thread your function starts does not inherit it, so `set_retrieval_documents` (or `record_documents`) from that thread does not feed the outer sample — call it on the traced thread before return, or pass documents into the metric yourself.
  - Metrics run on a background pool (default 2 threads; `init_tracing(metrics_workers=...)` or `OPENGRADE_METRICS_WORKERS`) fed by a bounded queue; when it is full the call is not scored and a warning is logged. Async metrics time out after 60 s; a sync metric cannot be interrupted. A raising or timed-out metric stores `label="ERROR"` with the exception as explanation (never breaks the traced call). For LLM judges raise `metrics_workers` or lower `metrics_sample_rate`.
  - Metrics run with instrumentation suppressed: LLM calls a judge makes and `@og.trace` helpers it calls do not create production traces (spans started manually with an OpenTelemetry tracer still do).
  - `trace(metrics=...)` accepts sync and `async def` (and `functools.partial` of a coroutine
    function; other async wrappers need `inspect.markcoroutinefunction`). Generator /
    async-generator functions are rejected with `metrics=`.
- These calls never raise. `log_score`, `log_feedback` and `trace(metrics=...)` never block the caller; `score_trace()` blocks for as long as the metric takes. Invalid input (bad value, label or trace id, or metadata over 16 KB serialized) logs a warning and returns `False`; setup problems (no project id, no active trace) warn at most once a minute.
- Scores are sent in the background (batches every 2 s, 100 scores or about 512 KB). A 413 (body over the server's 1 MiB limit) splits the batch in half and resends, dropping only a single score that is still too large. A batch rejected with 400/422 is resent item by item so only the bad scores are dropped; 401/403/404 and other 4xx drop the batch at once; only network errors and 5xx are retried once after a 1 s backoff, then dropped with a warning.
- `og.flush(timeout_millis=...)` is one total budget: spans, then pending metrics, then scores. At exit, spans, pending metrics, and scores share one ~5 s budget (span flush is capped at ~2 s of that).

### Alerts

The server checks alert rules every minute on production data and notifies a webhook (Slack or any URL) when one fires or resolves. A rule compares the metric with a fixed `threshold` (default), with the previous period (`condition="change"`: drift, threshold is a relative change) or with its recent history (`condition="anomaly"`: threshold is a z-score). Create them in the UI (Production → Alerts) or as code:

```python
client = og.client
client.alerts.create(
    name="Groundedness failing",
    metric="score_fail_rate",  # also error_rate, latency_p90_ms, traffic, cost_usd, ...
    score_name="groundedness",
    threshold=0.2,  # rates are 0-1
    window_minutes=60,
    webhook_url="https://hooks.slack.com/services/...",
    webhook_format="slack",
)
# Drift: groundedness mean down 20% vs the previous week.
client.alerts.create(
    name="Groundedness drift",
    metric="score_mean",
    score_name="groundedness",
    condition="change",
    operator="lt",
    threshold=-0.2,
    window_minutes=60,
    baseline_minutes=7 * 24 * 60,
)
# Anomaly: p90 latency 3 standard deviations away from the last 24 hours (hourly windows).
client.alerts.create(
    name="Latency anomaly",
    metric="latency_p90_ms",
    condition="anomaly",
    operator="abs",
    threshold=3,
    window_minutes=60,
)
client.alerts.list()  # with state: ok / firing / no_data
client.alerts.events()  # notification log
```

### Live runs → TestSet loop

```python
from opengrade import Client

with Client() as client:
    project_id = "..."  # existing project
    live = client.live_runs.submit(
        project_id,
        question="How many PTO days?",
        answer="Unlimited.",
        documents=[{"id": "pto", "text": "Full-time staff get 20 PTO days."}],
    )
    detail = client.live_runs.get(live.id)  # or list(..., failed_only=True)
    # After review, promote with reviewer-authored gold (never copy the prod answer):
    ds = client.datasets.create(project_id, name="from-live", task_type="rag_qa")
    client.live_runs.promote(
        live.id,
        dataset_id=ds.id,
        expected_output="Full-time employees get 20 PTO days per year.",
        expected_doc_ids=["pto"],
    )
    exp = client.experiments.create(project_id, name="after-promote", dataset_id=ds.id)
    client.experiments.evaluate_pack(exp.id)
```

See also [`scripts/live_run_demo.py`](https://github.com/19Alma98/ai-eval-platform/blob/main/scripts/live_run_demo.py) (`--promote`).

Eval binding still uses tracing attributes (no REST call):

```python
@og.trace
def run_item(question: str) -> str:
    opengrade.bind_evaluation(experiment_id=exp_id, dataset_item_id=item_id)
    ...
```

### Registry (app configs)

Versioned prompt + model configs live under `client.app_configs`:

```python
from opengrade import Opengrade, Settings

og = Opengrade(settings=Settings(project_slug="demo"))
project_id = og.set_project("demo").id
registry = og.client.app_configs
created = registry.create_app_config(
    project_id,
    "rag-faq",
    prompt={"system": "You are helpful."},
    model={"model_id": "demo"},
)
latest = registry.list_app_configs(project_id, latest=True)
registry.set_alias(project_id, "baseline", created.id)
```

Methods: `create_app_config`, `list_app_configs` (`name`, `latest`), `set_alias`, `get_aliases`.

End-to-end prompt A/B (same model, two App Config prompts): `uv run python 05_prompt_ab.py` in [`examples/sdk_tour`](https://github.com/19Alma98/ai-eval-platform/blob/main/examples/sdk_tour/README.md).

## Tier-1 compatibility matrix

| Key | Target library | OpenInference package | Notes |
|---|---|---|---|
| `openai` | `openai` | `openinference-instrumentation-openai` | OpenAI API and OpenAI-compatible endpoints (e.g. Ollama `/v1`) |
| `anthropic` | `anthropic` | `openinference-instrumentation-anthropic` | Documented; manual smoke outside default CI |
| `langchain` | `langchain` / `langchain_core` | `openinference-instrumentation-langchain` | Documented; manual smoke outside default CI |
| `llama_index` | `llama_index` | `openinference-instrumentation-llama-index` | Extra name: `llama-index` |
| `bedrock` | `boto3` (Bedrock runtime) | `openinference-instrumentation-bedrock` | Documented; manual smoke outside default CI |

Install the extra for the providers you use, then `og.init_tracing(instrument="auto")` activates every tier-1 entry whose target library and instrumentor package are importable. Use `instrument=["openai", "langchain"]` to restrict keys, or `instrument=False` for decorator-only tracing.

## Environment variables

| Variable | Purpose |
|---|---|
| `OPENGRADE_TRACKING_URI` | Platform URL for `Client()` and OTLP (default `http://localhost:8000`); `Settings(tracking_uri=...)` wins |
| `OPENGRADE_UI_URL` | Base URL for experiment/trace links in `announce()` / `ExperimentResult.url` (default: same as the API host) |
| `OPENGRADE_PROJECT` | Project name, created if it does not exist (same as `Opengrade(project=...)`) |
| `OPENGRADE_PROJECT_ID` | Project UUID header (`X-Project-Id`); used when not set on `Settings` / `set_project()` |
| `OPENGRADE_PROJECT_SLUG` | Project slug header (`X-Project-Slug`); the project must already exist |
| `OPENGRADE_SERVICE_NAME` | OpenTelemetry `service.name` (default `opengrade-app`) |
| `OPENGRADE_OTLP_ENDPOINT` | Optional override of the derived OTLP URL (e.g. a separate collector) |
| `OPENGRADE_DISABLED` | `1` / `true` / `yes` / `on` turns `init_tracing()` into a no-op and skips score/feedback HTTP (`log_score`, `log_feedback`, production metrics); decorators keep working |
| `OPENGRADE_VERSION` | Release of your app (`service.version`); production views, traces and alerts can be filtered and compared per version. `init_tracing(version=...)` wins |
| `OPENGRADE_ENVIRONMENT` | Deployment environment (`deployment.environment`, e.g. `prod`, `staging`). `init_tracing(environment=...)` wins |
| `OPENGRADE_METRICS_WORKERS` | Size of the `@og.trace(metrics=...)` background pool (default `2`, range 1–64); `init_tracing(metrics_workers=...)` wins |
| `OPENGRADE_TRACE_SAMPLE_RATE` | OTEL head sampling when opengrade owns the `TracerProvider` (`TraceIdRatioBased`, default `1.0`); `init_tracing(trace_sample_rate=...)` wins. Independent of `live_sample_rate` / `metrics_sample_rate` |
| `OPENGRADE_MAX_CAPTURE_BYTES` | Max UTF-8 bytes for captured input/output span attributes (default `32768`); `init_tracing(max_capture_bytes=...)` wins |

Project precedence for `init_tracing()`: keyword arguments > `set_project()` > env on `Settings`. If both `OPENGRADE_PROJECT_ID` and `OPENGRADE_PROJECT_SLUG` are set, id wins. `Settings(project_slug=…)` also wires control-plane calls (`log_score`, production metrics) via lazy slug→id resolution.

When the UI is served on a different host than the API, set `OPENGRADE_UI_URL` so result links open the UI instead of the API origin.

### HTTP stacks (proxy / TLS)

Control-plane calls (`Client`, `log_score`, experiments) use **httpx2**. OTLP span export uses OpenTelemetry’s HTTP exporter (**requests** / **urllib3**). Proxy and TLS settings can therefore differ: configure httpx2 for the API client, and `HTTP_PROXY` / `HTTPS_PROXY` / `REQUESTS_CA_BUNDLE` (or equivalent) for trace export. If the two stacks disagree in your environment, set `OPENGRADE_DISABLED=1` to stop tracing and score posts, or align both proxy/CA configs.

## Failure behavior

Tracing never breaks the host app:

- `init_tracing()` never raises. Without a project it logs a warning on the `opengrade` logger and stays a no-op; a broken instrumentor is skipped with a warning.
- Helpers called inside a traced function (`og.set_retrieval_documents`, `og.set_user`, `og.log_score`, …) never raise either: bad input is logged and ignored.
- If the platform rejects the traces (HTTP 404 unknown `project_id` / `project_slug`, 401 / 403 API key), one warning says so with the status and what to check; `og.flush()` returns `False`.
- Pending spans are flushed at interpreter exit (`atexit`, sharing the ~5 s exit budget with metrics/scores; span stage capped at ~2 s), so short scripts don't need `og.flush()`.
- If the platform is unreachable, spans are dropped: one warning when export starts failing, one info when it recovers. After a failure, export pauses for 30s, so a platform that is down adds no network calls and doesn't slow down exit.

## Content capture

The SDK may set OpenInference `input` / `output` attributes on decorated spans (`capture_input` / `capture_output`, default on). The platform API applies its own policy: it stores them by default (`CONTENT_CAPTURE_ENABLED=true`); with `CONTENT_CAPTURE_ENABLED=false` it drops input/output values, LLM prompts/messages and completions (including OpenInference flattened keys such as `llm.input_messages.0.message.content`) and the text of retrieved documents at ingestion. Timings, tokens, cost and document ids/titles/scores are kept, so retrieval metrics (hit@k, recall, MRR) still work, while judges that need document text (groundedness, context precision/recall) are SKIPPED. Turn capture off on either side when spans may carry data you must not store.

## Monorepo note

- SDK PyPI / import / CLI: `opengrade-ai` / `opengrade` / `opengrade`
- Server PyPI / import / CLI: `opengrade-ai-server` / `opengrade_server` / `opengrade-server` (share one venv via `opengrade-ai[ui]`)

## Manual smoke (not CI-required)

With the platform running and a project created:

**Anthropic**

```bash
cd sdk && uv sync --extra anthropic
uv pip install anthropic
uv run python -c "
import anthropic
from opengrade import Opengrade
og = Opengrade(project='demo')
og.init_tracing(instrument=['anthropic'])
c = anthropic.Anthropic()
@og.trace
def go():
    c.messages.create(model='claude-3-5-haiku-20241022', max_tokens=16, messages=[{'role':'user','content':'hi'}])
go()
og.flush()
"
```

**LangChain**

```bash
cd sdk && uv sync --extra langchain
# install langchain + your LLM backend as needed
uv run python -c "
from opengrade import Opengrade
og = Opengrade(project='demo')
og.init_tracing(instrument=['langchain'])
# invoke your LangChain chain here
og.flush()
"
```

See platform tracing docs: [`docs/04-tracing-and-otel.md`](https://github.com/19Alma98/ai-eval-platform/blob/main/docs/04-tracing-and-otel.md).

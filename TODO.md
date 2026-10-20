# TODO

Open items from the RAG evaluation reviews (2026-10-08, 2026-10-11) and the PyPI-readiness
review (2026-10-15). Fixed items are in git history.

## PyPI-readiness review (2026-10-15)

Source: parallel SDK / backend / frontend bug hunts + exploratory UI QA. "Confirmed" = reproduced
with a script (repros were in the session scratchpad); "code" = high-confidence code reading.
Priority: **P0** blocks a public release, **P1** fix before promoting it, **P2** polish / gaps.

### SDK — P0 (an observability SDK must never break the host app)

- [x] **`init()` hijacks the global OTel TracerProvider** — attach via `add_span_processor`; never shut
  down a provider we didn't create. (fixed)
- [x] **`@trace` always uses a sync wrapper** — dispatch on sync / async / gen / async-gen; span open
  until the result is fully consumed. (fixed)
- [x] **OTLP batches have no size cap / compression** — gzip, smaller batch size, split on failure
  instead of cooldown storm. (fixed)
- [x] **Transport errors escape raw** — `OpengradeError` / `OpengradeConnectionError` hierarchy;
  soft `set_project`; broader experiment catches. (fixed)
- [x] **Shared `AsyncClient` bound to the first event loop** — one client per loop
  (`WeakKeyDictionary`); swallow close errors. (fixed)
- [x] **`resolve_project_id` ignores `init(project_id=…/project_slug=…)`** — `init()` records the
  active project (lazy slug→id); env id wins over slug. (fixed)
- [x] **Inline dataset partially created then reused** — verify item count on reuse; resume
  `add_item` for remaining rows. (fixed)
- [x] **`finish()` crashes after all task work** — byte-chunk upserts / client-results; NaN/inf →
  null; per-chunk upload errors isolated. (fixed)

### SDK — P1

- [x] **Capture serialises full args/return even when not recording** (`_trace.py:45-47,169,182`).
  2M-int list arg adds ~360 ms/call even without `init()` / with `OPENGRADE_DISABLED`. Fix: skip when
  `not span.is_recording()`, serializer that stops at 32 KiB. (confirmed)
  Done (Approach A): skip serialize when `not span.is_recording()`; keep existing 32 KiB truncate.
- [x] **`@trace(metrics=…)` on methods deep-copies `self`** (`_production.py:295-311,351`) on the
  request thread (~315 ms for a RAG class with an in-memory index) and `Sample.input` becomes
  `{"args":[self,"hi"],…}`. Fix: drop bound `self` via signature, snapshot only needed fields off-thread.
  (confirmed)
  Done (Approach A): drop bound `self`/`cls` via signature; snapshot still on request thread.
- [x] **`evaluate(client=c, project="name")` uses the global client** for project lookup and mutates
  the global active project (`experiment.py:773-778,1087`). Fix: pass `client` through. (confirmed)
- [x] **`async def` task never awaited in `evaluate`** (`experiment.py:443-448`): output stored as
  `"<coroutine object …>"`, only a RuntimeWarning. Fix: await coroutine results via `run_sync` or add
  `aevaluate`. (confirmed)
  Done (Approach A): await via `run_sync`; no `aevaluate`.
- [x] **CSV loading** (`experiment.py:819-829,866-869`): documented `metadata` column sent as string →
  422 `dict_type`; empty cells sent as `""` instead of None → `rag_qa` dataset with a missing expected
  answer rejected (422). Fix: parse `metadata`/`context` as JSON, empty cell → None. (confirmed)
- [x] **`init(force=True)` never uninstruments** (`instrumentation.py:81`, `_otel.py:209`):
  OpenInference instrumentors are singletons, keep exporting to the shut-down provider → spans lost.
  Fix: `uninstrument()` before re-instrumenting. (code)
- [x] **No fork handler** (`_async.py:9-20`): forked child (gunicorn, multiprocessing) inherits
  `_LOOP` without its thread → async local metrics hang forever in experiments, 60 s timeout in
  production. Fix: `os.register_at_fork(after_in_child=…)` resets `_LOOP` and lock. (code)
- [x] **`init("auto")` imports langchain / llama_index / boto3 just to detect them**
  (`instrumentation.py:49-54`): seconds of startup + import side effects. Fix: `importlib.util.find_spec`.
  (code)

### SDK — P2

- [x] Exceptions recorded twice on the span (`_trace.py:174-176`). Fix: `record_exception=False`. (confirmed)
- [x] `OPENGRADE_DISABLED` only affects `init()`; `log_score`, `log_feedback`, score sender still send
  HTTP (`feedback.py:180-195`, `_production.py`). Fix: check `is_disabled()` in `_queue` / `after_call`. (code)
- [x] `import opengrade` takes ~0.87 s (protobuf, OTLP exporter, pydantic, httpx2 eager) → serverless
  cold starts. Fix: lazy imports. (confirmed)
- [x] Ints outside int64 passed as attributes → OTel logs a traceback per span and drops the attribute
  (`_trace.py:54-61`). Fix: stringify. (confirmed)
- [x] Windows console prints `→` literally; result links point to `localhost:8000` even when the UI
  runs elsewhere; summary prints "−0.083 unchanged" without saying the drop is not significant.
- [x] OTLP exporter and control-plane client use different HTTP stacks (requests vs httpx2) → proxy/TLS
  settings can differ. Document or align.

### Packaging / release — P0

- [x] No `LICENSE` file; no license / authors / project URLs / classifiers in either `pyproject.toml`.
- [x] No `py.typed` in the SDK wheel → typed API looks untyped to users.
- [x] `dev` extra (pytest, ruff, mypy) published to PyPI. Fix: move to `[dependency-groups]`.
- [x] `[ui]` / server pin only applied when `OPENGRADE_RELEASE_BUILD=1`. Fix: fail release builds
  that don't set it (or pin unconditionally in CI).
- [ ] **Migrations not shipped / not run outside Docker** (`infrastructure/db.py:85`,
  `pyproject.toml` packages only `src/opengrade_server`). `opengrade ui --backend-store-uri
  postgresql+asyncpg://…` on an empty DB → 500 on every write. Fix: package Alembic inside
  `opengrade_server`, run `upgrade head` programmatically on startup under an advisory lock. (confirmed)
- [ ] **Docker image not published** (`publish.yml` only does PyPI). Publish to GHCR/Docker Hub on tag,
  non-root user, documented env vars.
- [x] Decide `requires-python>=3.12` (PEP 695 generics) vs supporting 3.10/3.11 — **keep `>=3.12`**
  (PEP 695 / current CI+mypy). No backport to 3.10/3.11. Synced with "Python version bump" below.

### Packaging / getting started — P1

- [x] From a fresh clone `opengrade ui` needs `./scripts/package-ui.sh` (bash + `npm ci` + Next build)
  first — hard on Windows. Provide a cross-platform path (Python/npm script) or document clearly.
  → `python scripts/package_ui.py`; bash wrapper delegates.
- [x] `frontend/README.md` is still create-next-app boilerplate.
- [x] `opengrade ui` run from `backend/` silently loads `backend/.env` (content capture on,
  `LLM_API_BASE=host.docker.internal` unresolvable on host). Default judge `gemini/gemini-3.8-flash`
  needs a key, nothing tells the user. → startup banner + warnings.
- [x] Documented `cd backend && uv sync` strips dev extras from an existing venv; document
  `uv sync --all-extras` for contributors.
- [x] **`opengrade ui` starts silently when port 8000 is taken** (Windows: Docker on `0.0.0.0:8000`,
  ui binds `127.0.0.1:8000`; `localhost` clients hit the other server and wrote data into it).
  Fix: detect busy port and fail (`cli.py` connect probe). (confirmed)

### Backend — P0

- [x] **Trace upsert not atomic** (`repositories.py:163-285`, `errors.py:77`). Concurrent first
  batches for a new trace collide on `uq_traces_project_trace_id` → 409 (6 posts: 5×409 SQLite,
  4×409 Postgres); OTLP exporters don't retry 409 → spans lost. Fix: `INSERT … ON CONFLICT DO
  NOTHING` then reload/merge, or retry on IntegrityError. (confirmed both DBs)
- [x] **NaN/Inf protobuf double attributes** (`tracing/otel.py:44`) → Postgres JSONB insert fails →
  whole batch 500 (SQLite silently null). Fix: non-finite → string/None in `_attr_value_proto`.
  (confirmed pg)
- [x] **NUL bytes** (`\x00` in OTLP span name/attrs, `\u0000` in JSON API, e.g. dataset name) → 500 on
  Postgres. Fix: strip/replace at OTLP decode, reject (422) in the JSON guard middleware. (confirmed pg)
- [x] **Experiment stuck in `running`** (`application/evaluate.py:98-115`): `load_scoring_inputs` and
  evaluator lookup run outside the try/except after Start marked it running; any exception → every
  retry 409 until restart. Fix: move inside `try`. Same pattern in `live_interactions.py:398-408`:
  `replace_scores` on a failed session → PendingRollbackError, interaction stays `running`; fix with
  `session.rollback()` first. (confirmed / code)
- [x] **Concurrent `POST /evaluate` all start** (`evaluate.py:213-251,283-297`): read-then-write
  guard → 3 calls = 3 scorings, 3 runs, 3× LLM cost. Fix: atomic `UPDATE … SET status='running' WHERE
  id=:id AND status<>'running'`, rowcount 0 → 409. (confirmed both)
- [x] **Live scoring not claimed** (`routes/live_interactions.py:203`, `live_interactions.py:274`,
  `repositories.py:1471`): resubmit with same `external_id` while pending, rescore, or startup requeue
  schedules another scoring → 3 submits = 6 judge calls, 2–3 scores per kind, inflated monitoring.
  Fix: atomic `pending→running` claim, skip if no row updated. (confirmed both)
- [x] **`select_latest_runs` ignores run status** (`regression/aggregate.py:57-63`): PENDING/RUNNING or
  interrupted ERROR run with 0 results becomes "latest" → summary `mean_score: None`, release gate
  `unavailable`, exit 1, good previous run hidden. Fix: latest terminal run with results. (confirmed both)

### Backend — P1

- [x] **Run binding overwrites client context** (`tracing/run_binding.py:118-122`): documents set via
  `PUT /outputs` replaced by `{"latency_ms":…}` when the trace arrives → groundedness/retrieval lose
  documents. Fix: merge, keep existing `documents` if trace has no retrieval spans. (confirmed both)
- [x] **Child-only batches rename the trace** (`repositories.py:175,192-195`, `normalization.py:15-16,51-52`):
  later LLM-only batch changes trace name and input/output to the LLM prompt. Fix: update only when
  the batch contains the root (or a CHAIN) span. (confirmed both)
- [x] **Groundedness SKIPPED on live traffic when retrieval is in a nested function**
  (`tracing/live_binding.py` `_documents()`, `evaluation/trace_context.py` `_RETRIEVAL_KINDS`): docs on
  a child CHAIN span (`retrieval.documents`) are ignored; UI says "No documents were retrieved" while
  SDK metrics saw them. Fix: collect `retrieval.documents` from any descendant span. (confirmed via UI)
- [x] **Production/monitoring counts offline experiment traces** (`application/monitoring.py`):
  66 traces instead of 30, wrong error rate and p99. Fix: exclude traces bound to experiments
  (`opengrade.eval …`). (confirmed via UI)
- [x] **No gzip on `/v1/traces`** (`routes/otlp.py:53`, `otel.py:182`): OTel Collector otlphttp gzips by
  default → 400. Fix: decompress gzip/deflate, cap decompressed size. (confirmed)
- [x] **Monitoring naive vs aware datetime** (`routes/monitoring.py:84`): `since=…Z&until=…` (no tz) →
  TypeError → 500. Fix: treat naive as UTC (like `trace_scores.py:123`). (confirmed)
- [x] **IntegrityError → 409 with `str(exc)`** (`errors.py:77,93`) leaks SQL + bound params (possibly
  content). Fix: generic message, log details. (confirmed)
- [x] **Production alarms fire on tiny samples** (4 answers, 1 fail = 25% > 20%). Add a minimum n.
- [x] **Overview "Needs attention" ignores SDK metric / feedback alarms** that `/monitoring` shows.

### Backend — P2

- [ ] SQLite schema via `create_all` never alters existing tables → future column breaks existing
  `./opengrade.db`. `alembic check` drift: migrations create `ix_experiments_app_config_id`, model
  doesn't declare it (SQLite lacks the index). Fix: Alembic for SQLite too (batch mode). (confirmed drift)
- [ ] Protobuf OTLP bodies and multipart imports read fully into memory before any size check
  (`routes/otlp.py:53`, `routes/datasets.py:195`). Fix: check Content-Length, stream with a cap. (code)
- [ ] `asyncio.create_task` in `scoring_recovery.py:71` not referenced → may be GC'd mid-requeue.
  Fix: module-level task set. (code)
- [ ] Validation: overview accepts `until < since` (200); list endpoints (live-interactions,
  experiments, evaluators, datasets, app-configs) return `200 []` for unknown project instead of 404.
- [ ] Promote from queue requires `expected_doc_ids` (422) and the card has no field for it — exactly
  the no-retrieval failures that most need to become test cases.

### Server / container production-readiness — P1

- [ ] Multi-replica unsafe: startup recovery on one replica fails/requeues other replicas' running
  work. Needs leases or leader election (ties into "Pluggable job queue").
- [ ] `docker-entrypoint.sh` runs `alembic upgrade head` on every replica with no advisory lock.
- [ ] Single uvicorn worker; no `--proxy-headers`/`--forwarded-allow-ips`; no graceful drain of
  running scorings.
- [ ] Compose publishes API on `0.0.0.0:8000` (no auth) and Postgres on `0.0.0.0:5434` with default
  password `opengrade`. Bind to 127.0.0.1 by default.
- [ ] No server observability: no `/metrics`, no self-instrumentation, no request/job IDs in logs;
  `/health` doesn't check the DB (no readiness probe).
- [ ] No ingest backpressure: no rate limit / concurrency cap on `/v1/traces`, never 429/503 so
  exporters can't back off.
- [ ] SQLite mode: no WAL / `busy_timeout`, no backup/upgrade story.

### Frontend — P1

- [ ] **Live traffic search loses focus on every keystroke** (`features/live-runs/live-run-list.tsx:82-86,219`):
  toolbar unmounted while the new query loads. Fix: spinner only in the table, `placeholderData:
  keepPreviousData`, debounce search.
- [ ] **One failed 5 s refresh wipes the live list** (`live-run-list.tsx:220`). Fix: `isError && !data`,
  stale banner otherwise.
- [ ] **Overview time window frozen at page load** (`features/overview/overview-dashboard.tsx:47,75-80`);
  Refresh refetches the same window, "Updated just now" misleading. Same in `ProductionScoresCard`.
  Fix: anchor in state, reset on refresh (as `monitoring-dashboard.tsx:334,370`).
- [ ] **`experiment_metrics.<key>.max` checks rendered wrong** (`features/release/describe-check.ts:73-81`):
  shown as "≥ 2000.00 average score" while backend checks `<=`. Fix: dedicated branch, right sign, raw format.
- [ ] **Compare row verdict uses mean only** (`features/experiments/group-metrics-by-evaluator.ts:47` vs
  `experiment-compare-view.tsx:214-215`; backend flags pass-rate changes `regression/aggregate.py:221-224`):
  banner "1 metric worse" while every row "No real change". Also UI QA: compare says "0 worse" while the
  release gate fails the same pair with −8 pts; CI not shown. Fix: worse of mean/pass-rate verdicts, show CI.
- [ ] **Monitoring threshold field** (`features/monitoring/monitoring-dashboard.tsx:151-157`): invalid/empty
  value restores the old number in the field but deletes the saved custom alarm (falls back to 20%).
- [ ] **`compare-bars.tsx:66` checks `"regression"`, backend sends `"regressed"`**
  (`application/project_overview.py:50`) → non-significant drops shown red as "worse".
- [ ] **Experiment detail stale after scoring** (`features/experiments/use-experiments.ts:50-53`,
  `experiment-detail.tsx:364`): only status is polled; Refresh only refetches summary. Fix: refetch
  summary + answers on running→finished and on Refresh.
- [ ] **"Waiting for judge" filter sends only `pending`** (`live-run-list.tsx:83`), `running` items
  disappear. Fix: accept a status list in the backend.
- [ ] **Monitoring thresholds not tied to project** (`monitoring-dashboard.tsx:58-66`): A shows B's
  thresholds and next edit saves them under A. Fix: `key={projectId}`.
- [ ] **Traces count capped at 5000 silently** (`monitoring-dashboard.tsx:260`, backend
  `application/monitoring.py:25,237,254`); error rate / cost per trace computed on the sample. Show "5,000+"
  or return true count.
- [ ] **Next prefetch 404s on every page**: browser requests `/<page>/__next.!KGFwcCk.<page>.__PAGE__.txt`,
  export writes `__next.!KGFwcCk/<page>/__PAGE__.txt`. Fix mapping in `backend/.../ui.py` `resolve_ui_file`.
- [ ] **Annotation queue**: clicking "Correct" removes the card immediately, so "Add to test set" can't
  be done for that item and the next promote hits the wrong interaction.
- [ ] **Experiment detail hides params and run metrics** (`temperature`, `cost_usd`, `opengrade.latency_p50_ms`…);
  only in Compare-all (cut off on the right).
- [ ] Test-set picker on `/monitoring` shows a raw UUID after selection.

### Frontend — P2

- [ ] Mobile: at 375px sidebar never collapses, horizontal scroll (scrollWidth 586–689px).
- [ ] Sidebar background stops at viewport height on long pages.
- [ ] Production latency chart empty when all data is in one time bucket.
- [ ] 24h/7d chart axes show only HH:MM (`monitoring-charts-inner.tsx:34`).
- [ ] Live run detail error screen has no Retry (`live-run-detail.tsx:285-297`); malformed id shows
  generic "Something went wrong" instead of not-found.
- [ ] Accessibility: `components/data-table.tsx:67-77,111-124` rows not focusable, only j/k, `aria-selected`
  outside grid role; `features/traces/trace-waterfall.tsx:349,372` button nested in `role="button"`.
- [ ] No basePath/asset prefix (`next.config.ts:21-25`, `lib/api/client.ts:105`): UI can't be served
  under a sub-path behind a proxy. Fix: build-time `NEXT_PUBLIC_BASE_PATH`.
- [ ] Naming mismatch UI vs code (`hit_at_k` → "Hit rate", `must_contain` → "Required phrases"; import CSV
  `question`/`expected_answer` vs SDK `input`/`expected_output`); metrics set label
  `sdk:hit_at_k+must_contain+latency@689cc45d v1`; local Python metrics missing from `/metrics`.
- [ ] Test sets list: duplicate names per version, no question-count column; Overview "Test sets 2 —
  Questions with expected answers" reads like a question count.
- [ ] Import dialog on a locked test set doesn't say it creates a new version.
- [ ] Compare-all: same green for two metrics, uneven decimals; side-by-side defaults to first metric
  even when others changed; release gate rule names truncated.
- [ ] Empty states: Traces says "No traces match these filters" instead of how to send traces; Live
  traffic suggests `client.live_runs.submit` instead of `@opengrade.trace` + `init(live=True)`; live
  traces with no extractable question are silently skipped with no hint.
- [ ] Deleted saved project → "Unknown project" + failing requests; fall back to a valid project.

### Product gaps vs MLflow / Langfuse — P2

- [ ] **Auth**: API key (`OPENGRADE_API_KEY`) in SDK + server — needed before any non-localhost
  container deployment (see also "Optional auth" below).
- [ ] **PII redaction**: capture currently grabs every argument incl. `self`/secrets. Per-arg
  include/exclude, redaction hook, global capture switch.
- [ ] **Sampling** (head sampling) and configurable span size limits.
- [ ] `with opengrade.span(...)` context manager.
- [ ] `AsyncClient` parity (datasets, experiments), `aevaluate`.
- [ ] Pagination on SDK list calls; `set_project` / `evaluate` scan all projects/datasets/experiments.
- [ ] Experiments over time: x-axis by date, chart `log_metrics` (cost, p50/p95), dataset-version
  column/filter, metric columns in the experiments list.
- [ ] Compare shows params and experiment-metric deltas (backend already returns
  `ExperimentCompareResponse.experiment_metrics`), lower-is-better marking for latency/cost.
- [ ] Live view: session/user grouping, filter by SDK metric / feedback, SDK metrics + feedback in the
  list Scores column, "load more" beyond 50, time-range/metadata filters, auto-refresh on
  Overview/Monitoring/Traces.
- [ ] Drill-down from alarms / chart points to the traces that caused them.
- [ ] Filters persisted in the URL (live-runs, trace search, matrix rows); CSV/JSON export.
- [ ] Retention/TTL and per-project quotas (see "OTLP high volume" below).
- [ ] Custom time range / timezone and compare-to-previous-period on monitoring.

## Deferred

Do not block feature work. Pick these up when the trigger below each item shows up
(or an operator explicitly needs the flexibility).

### Performance

When optimizing, do N+1 batching first, then `failed_only` denormalization
(batching alone does not remove O(N) failed_only scans).

- [ ] **Live list N+1.** `ListLiveInteractions` loads scores and review per row (~3 queries ×
  page size; default 50, polled every 5s). Batch-load scores and reviews for a page.
  Fix when: list feels slow or query volume / pool wait shows up under normal browsing.
- [ ] **`failed_only` can scan the whole project** when few interactions failed (pages through all
  rows). Persist the verdict per interaction (e.g. `has_failed_score`) at scoring time and filter in
  SQL. Fix when: thousands+ interactions and the filter is used often (or empty full scans hurt).
  Do not replace with a fixed recent window — older failures must still surface.
  Trace scores now add one `list_by_trace_ids` query per *scanned* page; the denormalized verdict
  must also account for trace-score FAILs (they can arrive after the interaction).

### Production / ops

Postgres is source of truth for job state; the queue is a deployment detail. No Redis
(or other broker) in Compose or core deps — operators bring their own if they want one.

- [ ] **Pluggable job queue.** Routes/OTLP/recovery must not call FastAPI
  `BackgroundTasks` directly; call a `JobQueue.enqueue(name, payload)` port.
  Default backend: in-process (current BackgroundTasks behavior). Stable
  idempotent runners (`run_live_score`, `run_experiment_score`, …) stay the
  execution API. Optional later: Postgres `SKIP LOCKED` + `opengrade worker`,
  Redis/SQS/etc. as extras or docs (“bring your broker”), or a hook so operators
  push to their own orchestrator. Fix when: restarts drop work under load, API
  latency suffers from in-process judges, or multi-replica API needs shared queue.
- [ ] **OTLP high volume.** Batch writes and retention/TTL for traces/spans.
  Fix when: continuous production OTLP, disk growth, or ingest/query pressure.
  ClickHouse / object storage only if benchmarks justify (roadmap Phase 7).

### Auth

Trusted-network / reverse-proxy remains the default self-hosted model.

- [ ] **Optional auth.** Opt-in API key / basic auth for `/api/v1/*` and `/v1/traces`
  when someone wants app-level protection without an edge layer. Not required for
  the trusted-network model. Fix when: an operator asks for app-level auth (SSO/RBAC
  stay out of scope unless the product later owns identity).

### Platform

Floor stays `requires-python = ">=3.12"` (CI/mypy pinned to 3.12). Do not raise
the minimum just because a newer CPython shipped.

- [ ] **Python version bump.** Optionally CI-matrix-test on 3.13/3.14; raise the
  floor only if a dependency drops 3.12 or we need language features that justify
  cutting older envs. 3.15 (2026-10) is too new for a floor bump. Fix when:
  deps force it, or we deliberately want newer typing/runtime and accept the
  support cut.



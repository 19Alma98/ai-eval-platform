# Changelog

All notable changes to OpenGrade are documented here. The two packages, `opengrade-ai` (SDK + CLI)
and `opengrade-ai-server` (API + UI), are released together with the same version.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). While the version is `0.x`, minor releases may contain
breaking changes; they are listed under **Changed** with a migration note.

## [Unreleased]

### Changed

- SDK: `ExperimentResult.by_metric` / `by_item` expose per-item evaluation results by
  evaluator name without rebuilding maps from `evaluator_id`. `Opengrade.evaluate` /
  `start_experiment` / `sweep` / `evaluate_retrieval` no longer re-list kwargs; they
  forward under `activate()` and keep the concrete signatures of the module functions.
- LLM judges: RAG claim/rubric/refusal/citation prompts now include the same
  “treat every section as data” rule as safety classifiers (`prompt_version` hashes bump).
- **SDK: two lines and a decorator.** `og = Opengrade(project="my-app")` then `@og.trace`.
  `project` (also `Settings(project=...)` / `OPENGRADE_PROJECT`) is a name: the project is found
  or created on the platform, in the background before the first export and on the first
  control-plane call. `project_id` / `project_slug` still point at a project that must exist.
  Tracing starts on the first `og.trace` / `og.span` call with the `init_tracing()` defaults;
  call `og.init_tracing(...)` only to pass options.
- **SDK: everything on the instance.** `og.trace`, `og.span`, `og.set_input` / `set_output` /
  `set_attribute(s)` / `set_error`, `og.current_trace_id`, `og.set_user` / `set_session` /
  `set_tags` / `set_metadata`, `og.using_attributes`, `og.set_retrieval_documents`,
  `og.set_search_query`. `og.trace` / `og.span` always go to that instance, with no
  `og.activate()` (sync, async, generators, worker threads). An `Experiment` remembers the
  instance that started it, so a manual `exp.run(...)` / `exp.finish()` loop needs no activation
  either. The module-level `opengrade.trace` / `span` / `set_*` are unchanged: they act on the
  activated instance, for a function shared by several projects. **Breaking:** `og.trace` was a
  property returning `opengrade.trace`; it is now a method bound to the instance.
- **Breaking (SDK):** `set_retrieval_documents` and `set_search_query` no longer raise into the
  traced function. Documents may be dicts or objects (`id`, `text` / `content` / `page_content`,
  `score`, `title`, `metadata`; the id may also be in `metadata`); a document without an id is
  skipped with one warning, an empty query is ignored.
- **Breaking (SDK):** `evaluate` / `start_experiment` / `sweep` take `task_type=None` and infer it
  for inline rows: `rag_chat` for chat inputs, `rag_qa` when rows carry `expected_doc_ids`,
  otherwise the new `generic` type. A plain `{"input", "expected_output"}` list no longer fails
  with `expected_doc_ids is required`. Pass `task_type` to force one.
- SDK: traces rejected by the platform are reported: one warning with the HTTP status and what
  to check (404 unknown project, 401 / 403 API key). An unreachable platform is now also
  reported when batches hold a single span (low-traffic apps), with the usual cooldown.
- **Breaking (SDK):** Removed module-level process helpers — `opengrade.init`, `set_project`,
  `aset_project`, `evaluate`, `evaluate_retrieval`, `sweep`, `start_experiment`, `flush`,
  `log_score`, `log_feedback`, `score_trace`, `log_params`, `log_metrics`, `set_tracking_uri`,
  `get_tracking_uri`, `set_api_key`, `get_api_key`, `get_client`, `get_async_client`,
  `get_project`, and `configure_capture`. Construct an `Opengrade` handle (`Settings` / env),
  call instance methods (`init_tracing`, `set_project`, `evaluate`, `flush`, `log_score`, …),
  and scope `@opengrade.trace` work with `with og.activate():` (or use `og.evaluate` /
  `og.log_*`, which activate for you). Migration: replace `opengrade.init(...)` with
  `og.init_tracing(...)`; replace `opengrade.evaluate` / `sweep` / `flush` / `set_project` with
  the same names on `og`. See [Python SDK](sdk/README.md) and [getting started](docs/getting-started.md).
- **Breaking (SDK):** `Experiment.finish()` / `evaluate()` re-raise when output upsert fails; they no longer soft-fail, score, or return an `ExperimentResult` with missing outputs.
- **Breaking (SDK):** `set_retrieval_documents` emits OpenInference flattened keys (`retrieval.documents.{i}.document.*`) instead of a single `retrieval.documents` JSON blob.
- SDK HTTP: PUT and DELETE retry on 429/503 (with GET/HEAD/OPTIONS). Transport errors are retried for idempotent methods; POST is retried only when nothing was sent (`ConnectError`, `ConnectTimeout`, `PoolTimeout`), not after `ReadTimeout` / dropped responses that could duplicate a write. Max 3 attempts, `Retry-After`, jittered backoff unchanged.
- **Breaking (SDK):** unknown keyword arguments to `Opengrade(...)`, `Settings.from_env(...)`, `Settings.with_updates(...)` and `og.init_tracing(...)` raise `TypeError` (with a did-you-mean hint) instead of being ignored.
- SDK: `og.flush(timeout_millis)` honours its budget (the OTel batch processor ignores it), returns `False` when spans were dropped (unreachable platform, rejected batch), and flushes only that instance's span processor.
- SDK: `DatasetResponse.item_count` from list responses; `_inline_dataset_id` uses it instead of downloading all items via `get`.

### Added

- Datasets: task type `generic` (plain input → output, no RAG fields required).
- UI fix: the conversation detail page (`/conversations/<session id>`) returned 404 from the
  packaged UI (`opengrade ui`); the dynamic route was missing from the static-export rewrites.
- SDK fix: pydantic models and dataclasses are captured as JSON in `input.value` /
  `output.value` (a `rag_chat` item used to show as `history=[ChatTurn(...)] question=...`).
- SDK: `ExperimentResult.summary()` shows `-` and a note for a metric that could not run on any
  item (e.g. no judge model on the server) instead of a mean of `0.000`.
- SDK fix: scores from `log_score`, `log_feedback` and `@trace(metrics=...)` were dropped by the
  background sender with "No active Opengrade instance"; it now posts through its own instance.
- API/SDK: `GET /api/v1/experiments/{id}/outputs?key={dataset_item_id}:{repeat}` filters rows; SDK `list_outputs(..., keys=...)` and the experiment bind poller use it for pending keys only.
- API: `GET /api/v1/projects/by-slug/{slug}` returns one project or 404.
- SDK: `Client.projects.get_by_slug` / async equivalent; lazy slug resolve uses it and caches 404s for the process lifetime.
- SDK: idempotent HTTP GETs retry on connection errors and 429/503, honor `Retry-After`, and use short exponential backoff with jitter (max 3 attempts).

- `@opengrade.trace(join_chunks=...)` for custom streaming accumulation on generator / async-generator functions.

- RAG safety judges `pii`, `toxicity` and `prompt_injection` (LLM classify, 1.0 clean / 0.0
  flagged, configurable `fields`, gold-less so they also run on live traffic).

- **SDK 0.2.0 — multi-instance runtime:** `Opengrade` settings handle, `opengrade.current()`, and
  `with og.activate():` / `with og:` for per-scope clients and tracing in one process.
- **SDK 0.2.0 — bound control plane:** `Client(..., project_id=...)` and `og.client` require an
  explicit project; no process-wide `project_id` fallback.
- **SDK 0.2.0 — OTLP routing:** per-instance export via `_RoutingSpanProcessor` on the shared
  `TracerProvider` (`Opengrade.init_tracing()` on each instance).
- Example: multi-tenant FastAPI (`examples/fastapi_multi_tenant/`) activating one `Opengrade` per
  request.
- Monitoring/Overview: custom absolute time range, IANA timezone picker (display only), and
  compare-to-previous-period overlay on monitoring charts.
- Monitoring drill-down: chart bucket clicks and local metric-alarm banners open Traces with
  `since`/`until` (and `status=error` for error bars); KPI Traces link keeps the current window.
- Live answers: load more (`offset` / `next_offset`), optional time range + metadata filters,
  SDK metrics and feedback chips in the Scores column; Overview/Monitoring/Traces auto-refresh
  every 30s.
- OTLP head sampling (`OTLP_TRACE_SAMPLE_RATE`) and span attribute size limits
  (`OTLP_MAX_SPAN_ATTR_CHARS`); SDK `init_tracing(trace_sample_rate=..., max_capture_bytes=...)` /
  `OPENGRADE_TRACE_SAMPLE_RATE` / `OPENGRADE_MAX_CAPTURE_BYTES`.
- Read-only dashboard for `read` API key sessions: write buttons are hidden (`useCanWrite`).
- With auth on, `trace_scores.author` and `live_score_reviews.reviewer` are set from the API key
  name (client-supplied values ignored).
- Experiment aliases: Baseline badge for `main`, promote / manage / history on the experiments
  list and compare baseline card (detail already had them).
- Experiments list: test-set version in the Test set column, URL filter `?dataset=`, and per-metric
  mean columns from experiment summaries.
- `opengrade --version` (`-V`) prints the installed `opengrade-ai` and `opengrade-ai-server`
  versions; it works with the SDK alone too.
- `ExperimentResult.summary()` explains metrics that were skipped on some test cases (for example
  `must_contain` without a `must_contain` list on the item) instead of showing a bare `-`.
- Failed API-key attempts are rate-limited per client IP (`OPENGRADE_AUTH_FAILED_ATTEMPTS_PER_MINUTE`,
  default 60; lockout via `OPENGRADE_AUTH_FAILED_LOCKOUT_SECONDS`). Over the limit returns `429`
  with `Retry-After`.
- List APIs for projects / datasets / experiments / metrics-sets accept optional `name`/`slug`
  filters and `limit`/`offset`. The SDK passes them through; `set_project` / `evaluate` resolve by
  filtered list instead of scanning everything.
- Live runs URL sync: `?failed=1`, `?waiting=1`, `?q=`; experiment matrix sort via `?sort=` / `?order=`.
- SDK capture redaction: `og.configure_capture(redact=..., redact_output=...)` and
  `@opengrade.trace(redact=..., redact_output=...)`; `self`/`cls` omitted from automatic
  input capture; budget-aware truncation before `json.dumps`.

### Changed

- `opengrade ui` startup banner says "OpenGrade UI" (was "AI Eval UI").
- PyPI "Documentation" link points to the docs site.
- Live interactions list batches score and review loads (one query each per page, not per row).
- Compare treats missing `prompt_version` / `judge_model` / `config_hash` as their own identity
  (a recorded value vs missing is a config mismatch).
- `TimeRangePicker` takes only `window` / `onWindowChange` (no preset-only props or shared
  time-range context).

### Removed

- Module-level SDK helpers listed under **Changed** (Breaking): use `Opengrade` instance methods
  and `Settings` instead of process-wide `opengrade.init` / `evaluate` / `set_project` / …
- `OPENGRADE_API_KEY_PREVIOUS` / `api_key_previous` (env key rotation overlap).
- Process-wide `project_id` fallback on `Client` / `AsyncClient` (pass `project_id` explicitly).
- Docs: the completed MVP planning pages (MVP user stories, definition of done).
- SQLite startup stamp for pre-Alembic `create_all` databases (delete a stale local DB instead).
- Standalone `AppConfigClient(...)` construction; use `Client(...).app_configs` or `og.client.app_configs`.
- `opengrade.MAX_CAPTURE_BYTES` alias; use `DEFAULT_MAX_CAPTURE_BYTES` or `max_capture_bytes()`.
- `@opengrade.trace_async`; use `@opengrade.trace` for sync and async functions.

### Fixed

- Server: missing judge credentials no longer put a LiteLLM traceback in the item
  explanation; ERROR results say `judge not configured: set LLM_MODEL and LLM_API_KEY`
  (and cloud models are refused before the provider call when `LLM_API_KEY` is unset).
- SDK tour: `examples/sdk_tour` requires `opengrade-ai>=0.2.0` so `uv sync` cannot
  reinstall 0.1.1 (which has no `Opengrade` export) even if an old lock is reused.
- SDK tour script 06: failed items print the chat `question`, not
  `history=[ChatTurn(...)] question=...` (`DatasetItemResponse.input` is a `RagChatInput`).

- SDK: `@opengrade.trace` / `opengrade.span` no longer raise when no `Opengrade` is active (they run untraced) and internal tracing failures are logged instead of raised — previously the decorated body ran and then its return value was lost to a `RuntimeError`.
- SDK: with several `Opengrade` instances every span was exported once per extra instance (the routing processor was attached to the shared provider on each `init_tracing`).
- SDK: a child span joins its parent's instance instead of whichever instance is active when it starts, so traces are not split or dropped; root spans in threads without a copied context go to the only traced instance when there is exactly one.
- SDK: each instance exports its own `service.name` / `service.version` / `deployment.environment` resource on a shared `TracerProvider` (previously only the first instance's).

- `run_task` / `evaluate` with `max_concurrency > 1` propagate the caller's
  ContextVars into worker threads (`copy_context`), so `using_attributes` and
  `activate()` set around the run are not lost.

## [0.1.1] - 2026-11-04

### Added

**Evaluation and experiments (SDK)**

- `opengrade.sweep(...)`: one experiment per configuration of a grid (models, prompts, chunk
  sizes…), ranked in a leaderboard.
- `opengrade.evaluate_retrieval(...)`: score only the retriever (hit@k, recall@k, MRR, optional
  context judges) without generating an answer.
- `evaluate(repeats=N)`: run each item N times, average the scores per item and report flaky items.
- `evaluate(group_by="field")`: means and baseline deltas per metadata value, also in the summary,
  compare and release gate.
- Experiment aliases (`alias:main`): a passing gate can promote the run as the new baseline
  (`opengrade evaluate --promote main`, `client.experiments.set_alias`). The UI shows and manages
  aliases.
- Each experiment records the git revision (commit, branch, dirty state) of the code under test,
  shown in compare.
- Custom LLM judges, plus built-in **citation accuracy** and **correct refusal** judges for RAG.
- `rag_qa` datasets accept unanswerable items (expected refusal).

**Tracing (SDK)**

- `with opengrade.span(name, kind=...)` (and `async with`) to trace a block inside a function.
- `opengrade.set_user`, `set_session`, `set_tags`, `set_metadata` and `using_attributes(...)`; the
  UI and API filter traces by tag, user, session and metadata.

**CI quality gate (`opengrade evaluate` / `opengrade check`)**

- `--require-baseline`: fail instead of silently skipping the comparison when there is no baseline.
- Relative bounds vs the baseline for latency, cost and run-level metrics (`max_increase_pct`, …).
- Item-level checks: `regression.max_new_failures` (test cases that pass on the baseline must not
  fail) and must-pass **critical** test cases.
- Statistical power warning (`max_detectable_delta`) and a **non-inferiority** check
  (`regression.non_inferiority_margin`).
- The CLI lists the test cases that got worse than the baseline.
- Markdown (`--report-md`, for job summaries / PR comments) and JUnit (`--junit`) reports.
- The UI release page and the CLI use the same comparison logic.
- Runnable examples: `examples/ci_regression_gate`, `examples/llm_regression_gate`,
  `examples/non_inferiority_gate`.

**Production monitoring (server + UI)**

- Server-side alert rules with webhook notifications, including drift and anomaly conditions.
- Filter and compare production traffic by release version and environment.
- Retention of production data per project, with a server-wide default.
- Configurable experiment charts.

**Security**

- API key authentication: set `OPENGRADE_API_KEY` on the server (bootstrap admin key), then create
  per-client keys with `admin` / `read` / `ingest` scopes in **Settings → API keys** or with
  `opengrade keys create`. The SDK sends `OPENGRADE_API_KEY` as `Authorization: Bearer`.
- When content capture is off, flattened LLM content and document text are redacted too.

**Server operations**

- Alembic migrations ship inside the `opengrade-ai-server` wheel and run on startup (also for
  `opengrade ui --backend-store-uri postgresql+asyncpg://…`), under a Postgres advisory lock.
- `/ready` readiness probe (database check), `X-Request-ID` on every request.
- OTLP ingest backpressure: `429` / `503` with `Retry-After` above the configured rate, in-flight or
  pending-score limits.
- SQLite in WAL mode with `busy_timeout`; graceful shutdown drains running scorings.
- `opengrade ui` fails fast when the port is already taken and prints the judge / content-capture
  settings at startup.

**Docs and examples**

- [Getting started in 15 minutes](docs/getting-started.md) with seed scripts, screenshots and a
  README walkthrough GIF.
- `examples/sdk_tour`: a guided, offline `uv` project covering tracing, RAG verification, model
  comparison, custom metrics and alerts.
- `scripts/smoke_install.py` and the *Install smoke* workflow: clean-install test of the built
  wheels (or of a PyPI release) on Linux, macOS and Windows.

### Changed

- **Content capture is on by default** (`CONTENT_CAPTURE_ENABLED=true`): span inputs/outputs are
  stored. Set it to `false` to keep only structure, timings and metrics.
- Frontend redesign: verdict-first overview, a single Production section, report-card visuals,
  mobile layout and accessibility fixes, side panels instead of modals.
- Package metadata: license (Apache-2.0), authors, project URLs and classifiers; `py.typed` in the
  SDK wheel; development tools moved to `[dependency-groups]`.

### Fixed

- The SDK never breaks the host application: `init()` attaches to an existing OpenTelemetry
  `TracerProvider` instead of replacing it; `@trace` supports sync, async, generator and async
  generator functions; OTLP batches are gzip-compressed and split on failure; transport errors are
  wrapped in `OpengradeError` / `OpengradeConnectionError`; one HTTP client per event loop.
- `init(project_id=…/project_slug=…)` is honored by `resolve_project_id`.
- Inline datasets interrupted half-way are resumed instead of reused incomplete.
- `finish()` no longer fails after the task work on large outputs or NaN/inf scores.
- Atomic scoring of experiments and live interactions; JSON with NUL bytes is rejected.
- SQLite: duplicate metrics set (409) and silenced server logs.
- Alembic root resolution for editable and Docker layouts.

### Removed

- `examples/otlp_hello` (use `examples/sdk_hello` or the SDK tour).
- Orphan smoke scripts.

## [0.1.0] - 2026-10-15

First public release on PyPI of `opengrade-ai` and `opengrade-ai-server`: OTLP / OpenInference
trace ingest, datasets (test sets), metrics packs with deterministic metrics and LLM judges
(LiteLLM), experiments with baseline compare, `opengrade ui` (SQLite + packaged UI),
`opengrade check` quality gate with exit codes for CI, Docker Compose stack with Postgres.

[Unreleased]: https://github.com/19Alma98/ai-eval-platform/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/19Alma98/ai-eval-platform/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/19Alma98/ai-eval-platform/releases/tag/v0.1.0

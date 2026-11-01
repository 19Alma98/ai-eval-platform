# API Specification — v0.1

Base path:

`/api/v1`

## Authentication

v0.1 does not require application-level authentication.

Assumption: the API and OTLP ingestion endpoints run on a trusted network (localhost, private Docker/Kubernetes network, or operator-managed reverse proxy).

Optional later (non-blocking for MVP):
- static API key for machine clients;
- accept an upstream identity header from a reverse proxy.

Do not block the platform MVP on SSO, sessions, or RBAC.

## Projects

```http
GET /projects
POST /projects
GET /projects/{project_id}
DELETE /projects/{project_id}
```

### Overview

```http
GET /projects/{project_id}/overview?since={iso}&until={iso}
```

`since` required; `until` optional (default now). Returns live range KPIs + series, offline project snapshot (datasets, default metrics set, latest experiment, optional compare/`pass_rate` metrics, regressions), calibration alerts, and `warnings` for degraded sections. Unknown project → 404. Compare failures degrade to `compare: null` with HTTP 200. Live `n_failed` / `fail_rate` / attention use the same fail rule as `failed_only` on live interactions: judge FAIL, or any joined trace score with label `FAIL` (SDK metric under threshold, thumbs-down); `ERROR` does not count. `mean_score` stays judge-only.

`warnings` codes (non-exhaustive): `compare_unavailable`, `calibration_unavailable`, `live_truncated` (live interactions in the window exceeded the 10k aggregate cap — KPIs and series may undercount).

## Traces

Ingest via OTLP/HTTP (outside `/api/v1` prefix):

```http
POST /v1/traces
```

Headers: exactly one of `X-Project-Id` or `X-Project-Slug`. Accepts OTLP JSON or protobuf.

Fetch a stored trace by OpenTelemetry trace id (hex) for bound **Run** item timelines and debugging:

```http
GET /projects/{project_id}/traces/{trace_id}
```

## Datasets

```http
GET /projects/{project_id}/datasets
POST /projects/{project_id}/datasets
GET /datasets/{dataset_id}
POST /datasets/{dataset_id}/items
POST /datasets/{dataset_id}/items/import
```

`rag_qa` items require non-empty `metadata.expected_doc_ids` on create/import. CSV columns: `question`, `expected_answer`, `expected_doc_ids` (pipe-separated ids).

Once a dataset has any evaluation run, item mutations (add, import, live promote) automatically create the next `name` version (copying items from the latest tip), and apply the write there. Repeated writes against an immutable `dataset_id` reuse that writable tip instead of forking again. The original `dataset_id` stays immutable for historical experiments. `GET /datasets/{id}` includes `immutable`; import responses include `dataset_id`, `version`, and `forked_from_dataset_id`.

## App configs (registry)

```http
POST /projects/{project_id}/app-configs
GET /projects/{project_id}/app-configs
GET /app-configs/{app_config_id}
GET /projects/{project_id}/app-configs/by-name/{name}/versions
PUT /projects/{project_id}/app-config-aliases/{alias}
GET /projects/{project_id}/app-config-aliases
DELETE /projects/{project_id}/app-config-aliases/{alias}
```

`POST` body: `name` (required), optional `description`, `prompt`, `model`, `retrieval` (objects, default `{}`). Response includes assigned `version` and `content_hash`.

`GET .../app-configs` query params:
- `name` — filter to one config family
- `latest` — when `true`, return only the highest version per `name`

`PUT .../app-config-aliases/{alias}` body: `{ "app_config_id": "uuid" }`. The config must belong to the same project. Response includes alias metadata and a summary of the pinned config (`id`, `name`, `version`).

Errors: 404 project or app config not found; 400 validation (empty name, alias/config mismatch).

## Experiments

```http
GET /projects/{project_id}/experiments
POST /projects/{project_id}/experiments
GET /experiments/{experiment_id}
POST /experiments/{experiment_id}/evaluate
POST /experiments/{experiment_id}/evaluate-pack
GET /experiments/{experiment_id}/runs
GET /experiments/{experiment_id}/summary
GET /evaluation-runs/{run_id}
PUT /experiments/{experiment_id}/outputs
GET /experiments/{experiment_id}/outputs
POST /experiments/{experiment_id}/client-results
PUT /experiments/{experiment_id}/metrics
GET /experiments/{experiment_id}/metrics
PATCH /experiments/{experiment_id}/params
```

`POST .../evaluate-pack` scores using a resolved **metrics set** (see below). Optional JSON body:

```json
{
  "metrics_set_id": "uuid-or-null",
  "save_as_default": false
}
```

An empty body (or omitted body) is valid and equivalent to defaults. Resolution order: request `metrics_set_id` → experiment `metrics_set_id` → project default metrics set (created on demand). When `save_as_default` is true and the request supplies `metrics_set_id`, the experiment pin is persisted after resolve. Foreign or missing set IDs return 404. Ad-hoc `POST .../evaluate` with explicit `evaluator_ids` is unchanged and ignores metrics sets.

OTLP traces with `opengrade.experiment_id` and `opengrade.dataset_item_id` on root/CHAIN spans upsert experiment item outputs on ingest.

`POST /projects/{project_id}/experiments` body (in addition to `name`, `dataset_id`):

- `model_config` — optional free-form object when not binding an app config
- `app_config_id` — optional UUID; mutually exclusive with `app_config_alias`
- `app_config_alias` — optional alias name resolved within the project
- `metrics_set_id` — optional UUID; must belong to the same project (404 otherwise)
- `version`, `baseline_experiment_id` — optional

Experiment responses include `metrics_set_id` when pinned.

When `app_config_id` or `app_config_alias` is set, the server snapshots the referenced app config into `model_config` and sets response `app_config_id`. Supplying both app config fields returns 400; unknown alias returns 400; missing config returns 404.

`POST /experiments/{experiment_id}/evaluate` runs the selected evaluators against the experiment dataset and persists evaluation runs/results. (`POST .../run` and `POST .../cancel` remain future; evaluate is the v0.1 execution path.)

### Experiment item outputs

Bulk upsert per-dataset-item outputs for an experiment (overrides used at evaluation time):

```http
PUT /experiments/{experiment_id}/outputs
```

Request body:

```json
{
  "items": [
    {
      "dataset_item_id": "uuid",
      "actual_output": "optional",
      "context": {},
      "metadata": {}
    }
  ]
}
```

Omitted fields in each item are left unchanged on update; `"context": null` clears context.

Optional `"repeat": 0..99` (default `0`) stores repeated runs of the same item separately (unique per experiment, item and repeat). Every repeat is scored; results carry the same `repeat`, and `POST .../client-results` accepts it per result. Aggregates weigh each item once (mean over its applicable repeats): summary rows add `n_repeats` and `n_flaky` (items whose PASS changed between repeats), compare pairs item means, and compare-items shows the item mean with `metadata.repeats` (`n`, `pass_rate`, `std`, `flaky`, per-repeat `scores` / `labels`). OTLP binding reads `opengrade.repeat` next to `opengrade.dataset_item_id`.

Response: `{ "upserted": N, "items": [ ExperimentItemOutput ] }`.

```http
GET /experiments/{experiment_id}/outputs
```

Returns all stored output rows for the experiment. Errors: 404 experiment not found; 400 dataset item not in experiment dataset (PUT).

### Client-submitted scores

Stores scores that the client computed itself, for example an SDK-side Python metric:

```http
POST /experiments/{experiment_id}/client-results
```

```json
{
  "metrics": [
    {
      "name": "my_metric",
      "threshold": 0.5,
      "config": {"version": 2},
      "results": [
        {"dataset_item_id": "uuid", "score": 0.8, "label": null, "explanation": null, "metadata": {}}
      ]
    }
  ]
}
```

Each metric becomes a regular evaluation run on a project evaluator of type `custom` and kind `client`, named after the metric. The evaluator is created on first use and reused after that, so summary, compare, compare items, release check and the UI treat client metrics like server metrics. Response `201`: the created runs, with their results (`EvaluationRun[]`).

- **Labels**: the same PASS/FAIL rule as server scoring (`item_verdict`). A label (`PASS`/`FAIL`/`ERROR`/`SKIPPED`) and a score below `threshold` both count. With no threshold, a score of 0 fails and any other score passes. A result with neither a score nor a label is `SKIPPED`. The run status is derived from the labels the same way the server runner derives it.
- **Freshness**: the run stores the experiment's current inputs fingerprint. Submit after `PUT .../outputs`: when outputs or the test set change later, the run goes stale like a server run. Each submission adds a new run, and the latest fresh run per metric wins.
- **Comparability**: the run's `config_hash` is computed from `config`. Change `config` (e.g. a `version`) when the metric code changes, and compare will report `config_mismatch` instead of a delta.
- Items left out of `results` are simply not scored.

Errors:
- 404: experiment not found.
- 400: the request is rejected as a whole, so nothing is written. Causes: an empty or duplicate metric name, a duplicate `dataset_item_id` within a metric, an item outside the experiment's dataset, or an unknown label.
- 422: a non-finite score or threshold (`NaN`, `Infinity`). Every endpoint rejects these in a JSON body.
- 409: the name is already used by a server evaluator in the project.

Client evaluators cannot be run by the server. Passing one to `POST .../evaluate` returns 400, and using its id in a metrics set entry is rejected.

### Experiment params and metrics

MLflow-style logging on an experiment.

```http
PUT /experiments/{experiment_id}/metrics
```

```json
{"metrics": {"cost_usd": 1.42, "accuracy": 0.91}}
```

Stores one final value per key (no steps); the last write wins. Keys use 1-200 letters, digits or `_ . - /`, and a request carries at most 1000 metrics. Keys starting with `opengrade.` are reserved by convention for the SDK (`opengrade.error_rate`, `opengrade.latency_p50_ms`, `opengrade.latency_p95_ms`), which overwrites them on every `finish()`, so do not write them yourself. Response `200`: `{"experiment_id", "metrics": {...}}` with **all** the experiment's metrics. `GET` returns the same shape.

```http
PATCH /experiments/{experiment_id}/params
```

```json
{"params": {"temperature": 0.2}}
```

Shallow-merges into `model_config` and returns the experiment. Returns 409 once an evaluation has started (the experiment has left the `created` status or has any evaluation run; scored results must keep describing their config) and for experiments created from an app config (their params are the snapshot).

Errors: 404 experiment not found; 400 empty map, bad key, more than 1000 metrics, a value that is not a number (booleans included), or a number that overflows to infinity (e.g. `1e400`); 422 literal `NaN`/`Infinity` in the JSON; 409 params locked.

### Summary

```http
GET /experiments/{experiment_id}/summary
```

Optional query params:

- `run_ids` — explicit runs (must belong to the experiment); default = latest run per evaluator
- `evaluator_ids` — filter after run selection

Response includes per-evaluator aggregates: run `status`, `mean_score`, `pass_rate`, item counts (`n_scored`, `n_error`, `n_skipped`), and `experiment_metrics` (`{key: value}`).

### Experiment aliases (promoted baselines)

```http
PUT /projects/{project_id}/experiment-aliases/{alias}
GET /projects/{project_id}/experiment-aliases
GET /projects/{project_id}/experiment-aliases/{alias}
GET /projects/{project_id}/experiment-aliases/{alias}/history?limit=50
DELETE /projects/{project_id}/experiment-aliases/{alias}
```

An alias (e.g. `main`) points to the experiment that is the current baseline. `opengrade evaluate --promote main` moves it when the quality gate passes; `baseline: alias:main` reads it (see `docs/08-cli-ci.md`).

`PUT` body:

```json
{"experiment_id": "uuid", "note": "gate passed (version 1a2b3c4)", "force": false}
```

The experiment must belong to the project and must not be `running`, `failed` or `cancelled`. When the alias already points to an experiment with another `dataset_id` or `metrics_set_id`, the move is refused unless `force: true` (the two runs measured different exams). Response: `name`, `experiment_id`, `updated_at`, `experiment` (`id`, `name`, `version`, `dataset_id`, `metrics_set_id`, `status`, `created_at`), `previous_experiment_id`, and `changed` (`false` when the alias already pointed there; no history entry is written).

Every move appends a history entry (`experiment_id`, `previous_experiment_id`, `note`, `created_at`); `GET .../history` lists them newest first. Deleting the alias keeps its history; deleting the target experiment removes the alias.

Errors: 404 project, experiment or alias not found; 400 empty alias name; 409 experiment running/failed/cancelled, or exam mismatch without `force`.

## Evaluators

```http
GET /projects/{project_id}/evaluators
POST /projects/{project_id}/evaluators
```

## Metrics sets

```http
GET /projects/{project_id}/metrics-sets
POST /projects/{project_id}/metrics-sets
GET /metrics-sets/{metrics_set_id}
PATCH /metrics-sets/{metrics_set_id}
POST /metrics-sets/{metrics_set_id}/version
DELETE /metrics-sets/{metrics_set_id}
DELETE /metrics-sets/{metrics_set_id}/entries/{entry_id}
```

Each set has versioned `name`, optional `description`, `is_project_default`, and ordered **entries** (`kind`, `enabled`, `threshold`, `config`, `evaluator_id`, `is_default`). Seed entries on the project default set have `is_default=true` and cannot be removed while referenced.

## Metrics pack (alias)

```http
GET /projects/{project_id}/metrics-pack
PUT /projects/{project_id}/metrics-pack
POST /projects/{project_id}/metrics-pack/ensure
```

These routes are aliases over the project **default metrics set** (same UUID as `GET .../metrics-pack`). `ensure` creates the default RAG set and links built-in evaluator entities (`hit_at_k`, `recall_at_k`, `mrr`, `context_precision`, `must_contain`, `groundedness`, `correctness`, `latency`). `PUT` returns 409 when an experiment pins that default set.

## Live interactions (Live runs)

SDK-first prod hub. Ingest returns **202**; judge runs in background (gold-less metrics: `groundedness`, `answer_relevance`).

```http
POST /projects/{project_id}/live-interactions
GET /projects/{project_id}/live-interactions
GET /projects/{project_id}/live-interactions/calibration
GET /live-interactions/{interaction_id}
POST /live-interaction-scores/{score_id}/review
POST /live-interactions/{interaction_id}/promote
POST /live-interactions/{interaction_id}/rescore
```

`POST .../live-interactions` body: `question`, `answer`, optional `documents`, `metadata`, `external_id`, `metrics_set_id`.

List query: `judge_status`, `search`, `failed_only`, `limit`. Response shape: `{ items, judge_warnings }`. Each score may include nested `review` (per-score human review). `judge_warnings` is computed server-side over the last 50 live scores per kind (unfiltered by list query params); entries use the same `warnings` / `warning_detail` contract as offline runs when `judge_output_invalid` exceeds 20%.

`GET .../calibration` — judge/human agreement by `kind` × judge `model` (also `method`, `prompt_version`). Optional query `since` (ISO datetime; default last 90 days). Rows include `n_reviewed`, `n_agree`, `n_disagree`, `agreement_rate`, `n_explanation_edits`, `explanation_edit_rate`. Excludes score labels `ERROR` / `SKIPPED`.

`POST .../live-interaction-scores/{score_id}/review` body: `verdict` (`agree`|`disagree`), optional `corrected_explanation`, `note`, `reviewer`. Confirms or rejects that score’s PASS/FAIL; optional corrected explanation leaves the judge `explanation` unchanged. Rescore deletes score reviews (cascade).

`POST .../promote` body: `dataset_id`, required `expected_output` (reviewer-written gold; the production answer is never used as default), optional `expected_doc_ids` (required for `rag_qa` datasets) → creates a dataset item. Retrieved doc ids are stored as `metadata.retrieved_doc_ids_at_promotion` for reference only; they are never copied into `expected_doc_ids`.

## Trace scores (production scores and feedback)

Scores attached to an OTel trace: SDK metrics (`source="sdk"`), end-user feedback (`source="human"`), external judges (`source="judge"`). Stored per `(project, trace_id, name, source, author)`; writing the same key again replaces the value. There is no foreign key to `traces`: a score may arrive before its trace.

```http
POST /projects/{project_id}/trace-scores
GET /projects/{project_id}/trace-scores/summary
```

### `POST /api/v1/projects/{project_id}/trace-scores` → 202

```json
{"scores": [
  {"trace_id": "4bf92f3577b34da6a3ce929d0e0e4736", "name": "cites_source", "value": 0.0, "threshold": 0.5},
  {"trace_id": "4bf92f3577b34da6a3ce929d0e0e4736", "name": "user_feedback", "value": 1, "source": "human", "author": "user-42", "explanation": "great answer"}
]}
```

Response: `{"accepted": 2}` (the number of distinct keys stored). 1-500 items.

Item fields:

| Field | Notes |
|---|---|
| `trace_id` | required; 32 hex characters, case-insensitive (stored lower-case) |
| `name` | required; 1-200 characters, not blank |
| `value`, `threshold` | optional JSON numbers; strict (strings and booleans are rejected), finite |
| `label` | optional `PASS`, `FAIL`, `ERROR` or `SKIPPED` (case-insensitive) |
| `explanation` | optional; up to 4000 characters |
| `source` | `sdk` (default), `human` or `judge` |
| `author` | optional; up to 200 characters; part of the upsert key (missing = empty) |
| `metadata` | optional object; at most 16 KB serialized (compact JSON, UTF-8), else 422 |

The server computes the stored label with the same rule as experiment scores (`item_verdict`): in order: an explicit `ERROR`/`SKIPPED`/`FAIL` label wins; a value below `threshold` is `FAIL`; an explicit `PASS` is `PASS`; no value gives `null`; with a `threshold` and a value not below it the result is `PASS` (even value 0 with threshold 0); with no `threshold`, value 0 is `FAIL` and anything else `PASS`. A thumbs-down (`value: 0`, no threshold) is therefore `FAIL`.

The batch is all-or-nothing: it is rejected with 422 when any item is invalid (bad trace id, empty name, unknown source or label, non-numeric or non-finite value). Duplicate keys in one batch: the last one wins. A request body over 1 MiB (`TRACE_SCORES_MAX_BODY_BYTES`) is rejected with 413. Unknown project returns 404.

### `GET /api/v1/projects/{project_id}/trace-scores/summary?since=&until=`

Default window: the last 24 hours (`until` defaults to now). Naive datetimes are read as UTC. The window filters on the score's `updated_at` and is inclusive: `[since, until]`. Response: `{ since, until, rows }`, one row per `(name, source)` with `count`, `mean` (mean of `value`; for `user_feedback` this is the share of thumbs-up) and `pass_rate` over PASS/FAIL labels (`null` when none). Unknown project returns 404; `since >= until` returns 400.

### Where they show up

- `GET /api/v1/projects/{project_id}/traces/{trace_id}` includes `scores`.
- `GET /api/v1/projects/{project_id}/live-interactions` and `GET /api/v1/live-interactions/{id}` include `trace_scores`, joined on `metadata.source_trace_id`. `failed_only=true` also keeps interactions with any trace score whose stored label is `FAIL`, whatever its source (e.g. an SDK metric under its threshold, or a thumbs-down); `ERROR` does not count. Judge calibration ignores trace scores.

## Production releases (version / environment)

Traces store `version` (OTel resource `service.version`, or span attribute `opengrade.version`) and `environment` (`deployment.environment`, `deployment.environment.name` or `opengrade.environment`).

```http
GET /projects/{project_id}/monitoring?since=&until=&environment=&version=   # filtered health
GET /projects/{project_id}/monitoring/facets?since=&until=                  # environments + versions seen, with trace counts
GET /projects/{project_id}/monitoring/versions?since=&until=&environment=   # health per version (top 10 by traffic)
GET /projects/{project_id}/traces?environment=&version=                     # trace list filters
```

With a filter, live-judge scores only count for answers whose source trace matches it. Alert rules accept `environment` and `version` to watch one deployment or release.

## Alerts (server-side)

Rules on production monitoring metrics, evaluated by the API process every `ALERTS_INTERVAL_SECONDS` (default 60; `ALERTS_ENABLED=false` turns the loop off). Same numbers as the Production page (experiment-bound traces excluded).

```http
POST   /projects/{project_id}/alert-rules            # create
GET    /projects/{project_id}/alert-rules            # list with current state
POST   /projects/{project_id}/alert-rules/evaluate   # evaluate now
GET    /projects/{project_id}/alert-events?rule_id=&limit=
GET    /alert-rules/{rule_id}
PATCH  /alert-rules/{rule_id}                         # omitted = unchanged, null clears optional fields
DELETE /alert-rules/{rule_id}
POST   /alert-rules/{rule_id}/test                    # send a test notification
```

Body: `name`, `metric` (`error_rate`, `latency_p50_ms` / `latency_p90_ms` / `latency_p99_ms`, `traffic`, `cost_usd`, `total_tokens`, `needs_review`, `score_mean`, `score_fail_rate`), `operator` (`gt` / `lt`), `threshold` (rates are 0–1), `window_minutes` (5–10080, default 60), `min_samples` (default 10 for rates/percentiles/scores, else 0), `score_name` + optional `score_source` (`judge`, `sdk`, `human`) for `score_*`, `webhook_url`, `webhook_format` (`json` or `slack`), `repeat_minutes`, `enabled`.

State: `ok`, `firing`, or `no_data` (fewer than `min_samples`). Becoming `firing` notifies once, going back to `ok` sends `resolved`; `repeat_minutes` re-sends while firing. Changing the condition resets the state. Every notification is logged as an alert event with its delivery status (`sent`, `failed`, `skipped` when no webhook). Webhook: the rule's URL, else `ALERT_WEBHOOK_URL`. The `json` payload has `text` (Slack-compatible), `event`, `project`, `rule`, `value`, `samples`, `url`, `at`; `slack` sends only `text`. Set `PUBLIC_BASE_URL` to include a link to the Production page.

Single API replica only: several replicas would each evaluate and notify.

## Retention

Production data older than the project's retention period is deleted every `RETENTION_INTERVAL_HOURS` (default 24; first run a minute after start): production traces (with spans), live interactions (with judge scores and reviews), trace scores and alert events. Traces bound to an experiment run and traces a test case was built from (`source_trace_id`) are kept; test sets, experiments and results are never touched.

```http
GET  /projects/{project_id}/retention             # setting + what a purge would delete now
PUT  /projects/{project_id}/retention             # {"retention_days": 30 | null}
POST /projects/{project_id}/retention/purge?dry_run=false
```

`retention_days` null falls back to the server's `RETENTION_DAYS` (unset: keep forever). Also in the UI (Projects → retention icon) and the SDK (`client.projects.set_retention(30)`).

## Comparison

```http
GET /experiments/{experiment_id}/compare/{baseline_id}
```

Optional query params:

- `evaluator_ids`
- `candidate_run_ids`
- `baseline_run_ids`

Default run selection: latest run per `evaluator_id` on each side. Comparison uses the intersection of evaluator IDs.

Response includes:

- aggregate metric deltas (`mean_score`, `pass_rate`)
- status per metric: `regression` | `improved` | `unchanged` | `unavailable` | `config_mismatch` | `insufficient_n`
- `regressions`, `improved`, `unchanged`, `config_mismatches`, `insufficient_n` subsets
- `candidate_runs` / `baseline_runs`: per shared evaluator `{ evaluator_id, run_id, metadata }` (includes run-level `warnings` / `warning_detail` when the judge model was unsuitable)
- `experiment_metrics`: one row per key on either side `{ key, candidate, baseline, delta }` — `delta = candidate − baseline` when both exist; no status, since the better direction is unknown
- `candidate_git` / `baseline_git`: the code revision each experiment ran at (`{ commit, branch, dirty, remote_url }`) or `null` when none was recorded

Classification is higher-is-better. Aggregate `delta = candidate − baseline` is always populated when both means exist. Status uses a paired bootstrap 95% CI on per-item differences (same `dataset_item_id`, both sides applicable / non-`SKIPPED`):

- `n_paired < 5` → `insufficient_n` (delta still shown)
- `|delta| < 0.01` → `unchanged` (trivial band; bootstrap skipped)
- otherwise bootstrap (`B=2000`, deterministic seed from evaluator + run ids + metric): CI entirely above 0 → `improved`; entirely below 0 → `regression`; CI includes 0 → `unchanged`

Optional fields `ci_low`, `ci_high`, and `n_paired` are set when the bootstrap runs (or `n_paired` whenever item results are paired).

### Item-level compare

```http
GET /experiments/{experiment_id}/compare/{baseline_id}/items
```

Query params:

- `evaluator_id` — required when both experiments have results from more than one evaluator; otherwise defaults to the sole shared evaluator
- `regressions_only` — default `false`; when `true`, only rows with `status == regression`

Preconditions: both experiments exist (404); same `dataset_id` (400 on mismatch); ambiguous evaluator without `evaluator_id` (400). Like aggregate compare, only current (non-stale) runs are used — runs scored before outputs or the test set changed are skipped; if either side has no current run, the response is 400 with guidance to score or re-score.

Each item row includes `input`, `expected_output`, `baseline` / `candidate` sides (`actual_output`, `context`, `score`, `label`, `explanation`, `run_id`), per-item `delta`, and `status` (`regression` | `improved` | `unchanged` | `unavailable`). Outputs resolve from experiment item outputs with fallback to legacy dataset item fields.

## Quality gate

```http
POST /projects/{project_id}/release-check
```

Policy keys (except `regression`, `latency`, `cost`, `experiment_metrics`) are evaluator names. See `docs/02-domain-model.md` for rule semantics.

Input:
```json
{
  "experiment_id": "exp_123",
  "baseline_experiment_id": "exp_baseline",
  "policy": {
    "hit_at_k": {"min": 0.8},
    "groundedness": {"min": 0.7},
    "correctness": {"min": 0.7},
    "latency": {"p95_max_ms": 30000},
    "regression": {"max_delta": -0.05}
  }
}
```

`experiment_metrics` gates experiment-level scalars: `{"experiment_metrics": {"cost_usd": {"max": 2.0}, "accuracy": {"min": 0.8}}}`. Each bound becomes a check named `experiment_metrics.<key>.min|max`; a key the experiment never logged is `unavailable` and fails the gate. A rule needs `min` or `max` (422 otherwise); `min` must be <= `max` and keys follow the metric key rules (400 otherwise).

Relative bounds compare with the baseline experiment: `latency.max_increase_pct`, `cost.max_increase_pct` and, per experiment metric, `max_increase` / `max_decrease` / `max_increase_pct` / `max_decrease_pct` (all `>= 0`). Example: `{"latency": {"p95_max_ms": 2000, "max_increase_pct": 20}, "experiment_metrics": {"opengrade.error_rate": {"max_increase": 0.01}}}` → checks `latency.p95`, `latency.p95.max_increase_pct` (actual = % change of p95) and `experiment_metrics.opengrade.error_rate.max_increase` (actual = change). Semantics: `docs/02-domain-model.md`.

`baseline_experiment_id` is required (400 otherwise) when `policy.regression` is set, when `groups.max_delta` is set without a top-level regression block, or when any relative bound is set, unless the experiment already has `baseline_experiment_id`.

`policy.regression` fails a shared evaluator when compare status is `regression` (same paired bootstrap 95% CI as `/compare`). Optional `max_delta` is a mean-score safety floor (also fail when the CI includes 0 but the mean drop is below the floor). Omit `max_delta` for bootstrap-only gating (`"regression": {}`). Compare status `insufficient_n` (paired n < 5) produces a check with status `unavailable` and fails the gate. Set `regression.allow_insufficient_n: true` to soft-pass those evaluators (small demo sets only). Latency p95 fails when any result has `missing_output: true` without `latency_ms`.

Response (HTTP 200 for both pass and fail):
```json
{
  "status": "failed",
  "experiment_id": "exp_123",
  "baseline_experiment_id": "exp_baseline",
  "checks": [
    {
      "metric": "quality.min",
      "actual": 0.91,
      "threshold": 0.85,
      "status": "passed"
    },
    {
      "metric": "latency.p95",
      "actual": 2610,
      "threshold": 2000,
      "status": "failed"
    }
  ]
}
```

Errors: 404 project/experiment not found; 400 invalid policy, missing baseline for regression, or invalid run selection.

## CLI contract

Phase 4 ships `opengrade check` (see `docs/08-cli-ci.md`). Additional CLI commands remain planned:

```bash
opengrade check --policy opengrade.yaml
```

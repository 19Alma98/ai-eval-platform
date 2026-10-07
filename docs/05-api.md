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

## Traces

```http
GET /projects/{project_id}/traces
GET /projects/{project_id}/traces/{trace_id}
POST /projects/{project_id}/traces
```

Filters:
- time range
- status
- service
- model
- user/session
- tag

Pagination:
- cursor-based

## Datasets

```http
GET /projects/{project_id}/datasets
POST /projects/{project_id}/datasets
GET /datasets/{dataset_id}
POST /datasets/{dataset_id}/items
POST /datasets/{dataset_id}/items/import
POST /datasets/{dataset_id}/items/from-trace
```

`rag_qa` items require non-empty `metadata.expected_doc_ids` on create/import. CSV columns: `question`, `expected_answer`, `expected_doc_ids` (pipe-separated ids).

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
```

`POST .../evaluate-pack` scores using a resolved **metrics set** (see below). Optional JSON body:

```json
{
  "metrics_set_id": "uuid-or-null",
  "save_as_default": false
}
```

An empty body (or omitted body) is valid and equivalent to defaults. Resolution order: request `metrics_set_id` → experiment `metrics_set_id` → project default metrics set (created on demand). When `save_as_default` is true and the request supplies `metrics_set_id`, the experiment pin is persisted after resolve. Foreign or missing set IDs return 404. Ad-hoc `POST .../evaluate` with explicit `evaluator_ids` is unchanged and ignores metrics sets.

OTLP traces with `aiobs.experiment_id` and `aiobs.dataset_item_id` on root/CHAIN spans upsert experiment item outputs on ingest.

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

Response: `{ "upserted": N, "items": [ ExperimentItemOutput ] }`.

```http
GET /experiments/{experiment_id}/outputs
```

Returns all stored output rows for the experiment. Errors: 404 experiment not found; 400 dataset item not in experiment dataset (PUT).

### Summary

```http
GET /experiments/{experiment_id}/summary
```

Optional query params:

- `run_ids` — explicit runs (must belong to the experiment); default = latest run per evaluator
- `evaluator_ids` — filter after run selection

Response includes per-evaluator aggregates: run `status`, `mean_score`, `pass_rate`, item counts (`n_scored`, `n_error`, `n_skipped`).

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

These routes are aliases over the project **default metrics set** (same UUID as `GET .../metrics-pack`). `ensure` creates the default RAG set and links built-in evaluator entities (`hit_at_k`, `must_contain`, `groundedness`, `correctness`, `latency`). `PUT` returns 409 when an experiment pins that default set.

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
- status per metric: `regression` | `improved` | `unchanged` | `unavailable`
- `regressions`, `improved`, `unchanged` subsets

Classification uses higher-is-better with `|delta| < 0.01` treated as unchanged.

### Item-level compare

```http
GET /experiments/{experiment_id}/compare/{baseline_id}/items
```

Query params:

- `evaluator_id` — required when both experiments have results from more than one evaluator; otherwise defaults to the sole shared evaluator
- `regressions_only` — default `false`; when `true`, only rows with `status == regression`

Preconditions: both experiments exist (404); same `dataset_id` (400 on mismatch); ambiguous evaluator without `evaluator_id` (400).

Each item row includes `input`, `expected_output`, `baseline` / `candidate` sides (`actual_output`, `context`, `score`, `label`, `explanation`, `run_id`), per-item `delta`, and `status` (`regression` | `improved` | `unchanged` | `unavailable`). Outputs resolve from experiment item outputs with fallback to legacy dataset item fields.

## Release gate

```http
POST /projects/{project_id}/release-check
```

Policy keys (except `regression`) are evaluator names. See `docs/02-domain-model.md` for rule semantics.

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

`baseline_experiment_id` is required when `policy.regression` is set unless the experiment already has `baseline_experiment_id`.

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

Phase 4 ships `aiobs check` (see `docs/08-cli-ci.md`). Additional CLI commands remain planned:

```bash
aiobs check --policy aiobs.yaml
```

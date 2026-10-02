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
POST /datasets/{dataset_id}/items/from-trace
```

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
GET /experiments/{experiment_id}/runs
GET /experiments/{experiment_id}/summary
GET /evaluation-runs/{run_id}
PUT /experiments/{experiment_id}/outputs
GET /experiments/{experiment_id}/outputs
```

`POST /projects/{project_id}/experiments` body (in addition to `name`, `dataset_id`):

- `model_config` — optional free-form object when not binding an app config
- `app_config_id` — optional UUID; mutually exclusive with `app_config_alias`
- `app_config_alias` — optional alias name resolved within the project
- `version`, `baseline_experiment_id` — optional

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

Response includes per-evaluator aggregates: `mean_score`, `pass_rate`, item counts.

## Evaluators

```http
GET /projects/{project_id}/evaluators
POST /projects/{project_id}/evaluators
```

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
    "quality": {"min": 0.85},
    "groundedness": {"min": 0.90},
    "latency": {"p95_max_ms": 2000},
    "cost": {"max_per_request_usd": 0.03},
    "regression": {"max_delta": -0.03}
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

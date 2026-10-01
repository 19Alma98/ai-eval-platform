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

## Experiments

```http
GET /projects/{project_id}/experiments
POST /projects/{project_id}/experiments
GET /experiments/{experiment_id}
POST /experiments/{experiment_id}/evaluate
GET /experiments/{experiment_id}/runs
GET /experiments/{experiment_id}/summary
GET /evaluation-runs/{run_id}
```

`POST /experiments/{experiment_id}/evaluate` runs the selected evaluators against the experiment dataset and persists evaluation runs/results. (`POST .../run` and `POST .../cancel` remain future; evaluate is the v0.1 execution path.)

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
## Release gate

```http
POST /projects/{project_id}/release-check
```

Input:
```json
{
  "experiment_id": "exp_123",
  "policy": {
    "quality": {"min": 0.85},
    "latency": {"p95_max_ms": 2000}
  }
}
```

Response:
```json
{
  "status": "failed",
  "checks": [
    {
      "metric": "latency.p95",
      "actual": 2610,
      "threshold": 2000,
      "status": "failed"
    }
  ]
}
```

## CLI contract

The CLI must use the same API/domain semantics:

```bash
aiobs init
aiobs dataset create support-v1
aiobs dataset add --from-trace TRACE_ID
aiobs experiment run support-v1
aiobs experiment compare EXP_A EXP_B
aiobs check --policy aiobs.yaml
```

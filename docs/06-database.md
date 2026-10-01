# Database Design

## Technology

PostgreSQL for v0.1.

Use UUID/ULID-like identifiers at the application boundary. Keep external IDs opaque.

## Core tables

```text
projects
traces
spans
datasets
dataset_items
evaluators
experiments
evaluation_runs
evaluation_results
release_policies
reviews
```

## JSONB

Use JSONB for:
- arbitrary metadata
- span attributes
- evaluator configuration
- model configuration

Do not put frequently filtered relational fields only inside JSONB.

Promote important query dimensions to columns:
- project_id
- timestamp
- model/provider
- status
- trace_id
- span kind

## Indexes

Initial:
- traces(project_id, start_time DESC)
- traces(project_id, status)
- spans(trace_id)
- spans(project_id, start_time DESC)
- evaluation_results(run_id, dataset_item_id)
- experiments(project_id, created_at DESC)

## Retention

v0.1:
- configurable application-level retention
- explicit delete endpoint later
- avoid hard-coded indefinite retention

## Scaling path

When trace volume becomes large:
- retain transactional metadata in PostgreSQL
- move analytical/event-heavy workloads to ClickHouse
- object storage for large payloads
- asynchronous ingestion

Do not introduce these components until benchmarks justify them.

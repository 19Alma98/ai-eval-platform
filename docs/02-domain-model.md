# Domain Model

## Project

Top-level organization/isolation boundary for platform data.

In v0.1 this is not a multi-tenant SaaS tenancy or auth realm. It groups traces, datasets, experiments and policies for a team or application running a self-hosted instance.

Fields:
- id
- name
- slug
- created_at

## Trace

Represents one execution of an AI application.

Fields:
- id
- project_id
- trace_id
- name
- status
- start_time
- end_time
- input
- output
- metadata
- environment
- user_id (optional)
- session_id (optional)

## Span

A timed child operation.

Fields:
- id
- trace_id
- parent_span_id
- span_id
- name
- kind
- start_time
- end_time
- status
- attributes
- events

OpenInference span kinds should be supported where available, including LLM, EMBEDDING and CHAIN.

## Dataset

Reusable evaluation collection.

Fields:
- id
- project_id
- name
- version
- description
- created_at

## DatasetItem

A single evaluation example.

Fields:
- id
- dataset_id
- input
- expected_output
- context
- metadata
- source_trace_id (optional)
- source_span_id (optional)

## Evaluator

A named implementation/configuration.

Fields:
- id
- project_id
- name
- type
- config
- version

Types:
- deterministic
- llm_judge
- custom

## EvaluationRun

Execution of an evaluator against a dataset/experiment.

Fields:
- id
- experiment_id
- evaluator_id
- status
- started_at
- finished_at

## EvaluationResult

Per-item score.

Fields:
- id
- run_id
- dataset_item_id
- score
- label
- explanation
- metadata
- duration_ms

## Experiment

A versioned evaluation execution.

Fields:
- id
- project_id
- name
- dataset_id
- model_config
- application_version
- baseline_experiment_id
- status
- created_at

## ReleasePolicy

Machine-readable quality gate.

Example:

```yaml
quality:
  min: 0.85
groundedness:
  min: 0.90
latency:
  p95_max_ms: 2000
cost:
  max_per_request_usd: 0.03
regression:
  max_delta: -0.03
```

## Review

Human judgement attached to a trace/span/evaluation result.

Fields:
- id
- target_type
- target_id
- label
- score
- comment
- reviewer
- created_at

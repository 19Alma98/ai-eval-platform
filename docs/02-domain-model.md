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

Prefer one dataset per evaluation task (for example People Ops RAG vs classification). Optional soft typing guides the UI with field hints and recommended evaluators; it does not validate item schemas.

Fields:
- id
- project_id
- name
- version
- description
- task_type (optional; allowlist: `rag_qa`, `classification`, `agent_tools`)
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

### `rag_qa` test set contract

When `task_type=rag_qa`, each item used in the RAG vertical must include:

- **question** — stored as `input` (string or structured JSON; portfolio/import use plain string)
- **expected_answer** — stored as `expected_output`
- **expected_doc_ids** — non-empty list in `metadata.expected_doc_ids` (CSV import uses pipe-separated ids)

`actual_output` and retrieved document text belong to a **run** (experiment item output or bound OTLP trace), not the test set.

## Metrics set (project-scoped)

Versioned grading configuration for RAG (and custom) evaluators on a project. One set per project may be marked `is_project_default` (seed name `Default` v1).

Fields:
- id, project_id, name, version, description
- is_project_default
- entries (ordered)
- created_at, updated_at

Each **MetricsSetEntry** has: `kind`, `enabled`, `threshold`, `config`, `evaluator_id`, `is_default` (seed rows on the default set), `created_at`.

Default seed entries (`is_default=true`, not deletable on the default set while referenced):

| kind | role |
|------|------|
| `hit_at_k` | expected doc id in top-k retrieved ids (binary) |
| `recall_at_k` | fraction of expected doc ids in top-k |
| `mrr` | reciprocal rank of first expected doc in top-k |
| `context_precision` | LLM judge: RAGAS average precision of retrieved chunks vs reference answer |
| `must_contain` | required phrases in the answer |
| `groundedness` | LLM judge on answer vs retrieved chunks |
| `correctness` | LLM judge vs expected answer |
| `latency` | per-item latency vs `config.max_ms` |

Custom sets are created with `POST .../metrics-sets`; versioning copies entries with `is_default=false`. Experiments may pin a set via `metrics_set_id`.

## Metrics pack (API alias)

HTTP `/metrics-pack` reads and writes the project default metrics set. Prefer `/metrics-sets` for named/custom sets.

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

## AppConfig

Versioned registry entry for prompt, model, and retrieval settings used when running evaluations.

Fields:
- id
- project_id
- name
- version (monotonic per `name` within a project)
- description (optional)
- prompt (JSON object)
- model (JSON object)
- retrieval (JSON object)
- content_hash (SHA-256 of canonical prompt/model/retrieval)
- created_at

Creating a config with the same `name` allocates the next `version`. Listing supports `name` filter and `latest=true` (one row per config family).

## AppConfigAlias

Named pointer to a specific `AppConfig` version within a project (for example `baseline`, `candidate`).

Fields:
- project_id
- name
- app_config_id
- updated_at

Aliases are unique per `(project_id, name)`. `PUT` creates or moves an alias; `DELETE` removes it.

## Experiment

A versioned evaluation execution.

Fields:
- id
- project_id
- name
- dataset_id
- model_config (free-form JSON, or snapshot from an app config when bound)
- app_config_id (optional; set when created from `app_config_id` or resolved `app_config_alias`)
- metrics_set_id (optional pin for pack scoring; overridable per evaluate-pack request)
- version
- baseline_experiment_id
- status
- created_at

On create, supply at most one of `app_config_id` or `app_config_alias`. When either is set, the API copies the referenced config into `model_config` (including `app_config_id`, `content_hash`, prompt/model/retrieval) and ignores a client-supplied `model_config`. Without app config fields, `model_config` remains free-form.

### Versioning

An experiment is an immutable record of *what was evaluated against what*. Every input it depends on is pinned to a version, so two experiments can be compared and an old result can be explained later:

| Input | How it is pinned |
| --- | --- |
| Test set | `dataset_id` points at one dataset version. Once a version has a scored run it is frozen: adding, importing or promoting items forks the next version (`version + 1`) instead of changing it. |
| App under test | `model_config` is a snapshot. With an app config it carries `app_config_id` and `content_hash`; app configs themselves are versioned per `name` (monotonic `version`). |
| Parameters | Logged params are locked once the experiment has evaluation runs (or when they come from an app config snapshot). |
| Grading | `metrics_set_id` pins a versioned metrics set. Each `EvaluationRun` is kept; LLM-judge results record `prompt_version` and `model` in their metadata. |
| Label | `version` is an optional free-form label (git SHA, release tag) set by the caller (default: the short commit SHA, `-dirty` suffix with uncommitted changes), e.g. `opengrade.evaluate(..., version="v1.4.0")`. |
| Code | `git` is `{commit, branch, dirty, remote_url}`, detected by the SDK from the local checkout (or CI env vars such as `GITHUB_SHA` / `CI_COMMIT_SHA` when there is no `.git`). Compare shows both commits and links the code diff for GitHub / GitLab remotes. Credentials are stripped from the remote URL. Opt out with `git=False` or `OPENGRADE_DISABLE_GIT=1`. |

Re-scoring an experiment adds a new `EvaluationRun`; it never overwrites earlier results. Compare and release checks read the latest *terminal* run with results.

## ReleasePolicy

Machine-readable quality gate. Phase 4 evaluates it statelessly (YAML/file or inline API body); the reserved keys are `regression`, `latency`, `cost` and `experiment_metrics`; every other key binds to an evaluator entity name.

Semantics:
- `{name}.min` — pass if latest-run `mean_score >= min`
- `latency.p95_max_ms` — pass if p95 of result `metadata.latency_ms` (nearest-rank) `<=` threshold. Rows without `latency_ms` (e.g. SKIPPED) are excluded from the sample. Any result with `metadata.missing_output: true` and no usable `latency_ms` fails the check (do not green-light incomplete runs on a latency subset).
- `cost.max_per_request_usd` — pass if mean of result `metadata.cost_usd` `<=` threshold
- `latency.max_increase_pct` / `cost.max_increase_pct` — relative bounds vs the **baseline** experiment: pass if the candidate p95 latency (resp. mean cost per request) is at most that many percent above the baseline's (`(candidate − baseline) / baseline × 100`). Checks `latency.p95.max_increase_pct` and `cost.mean_per_request_usd.max_increase_pct`; `actual` is the change in percent. Missing data on either side → `unavailable`; any increase from a baseline of 0 fails. Each block needs its absolute bound, its relative bound, or both.
- `regression` — for each shared evaluator, uses the **same bootstrap status as experiment compare** (`GET …/compare/{baseline}`): fail when status is `regression` (paired 95% CI entirely below 0). Optional `max_delta` is a mean-score **safety floor**: also fail when status is `unchanged`/`improved` but `mean_score` delta (candidate − baseline) `< max_delta`. Compare status `insufficient_n` (n < 5) yields check `unavailable` → overall failed. Opt-in `regression.allow_insufficient_n: true` restores soft-pass (skip those evaluators) for small demo sets. A bare `regression: {}` gates on bootstrap only.
- `experiment_metrics` — `{key: {min?, max?}}` gates experiment-level scalars logged via `PUT /experiments/{id}/metrics`; each bound becomes a check `experiment_metrics.<key>.min|max`. A key that was never logged is `unavailable` and fails the gate. Relative bounds vs the baseline run: `max_increase` / `max_decrease` (absolute change) and `max_increase_pct` / `max_decrease_pct` (percent of the baseline value), checks `experiment_metrics.<key>.<bound>`. `actual` is the change in the guarded direction (positive = moved that way; improvements are negative) and passes when `<=` the bound. Use `max_increase` for lower-is-better metrics (`opengrade.error_rate`, `opengrade.latency_p95_ms`) and `max_decrease` for higher-is-better ones.
- Rules that compare with a baseline (`regression`, `groups.max_delta`, any relative bound) require a baseline experiment.
- Missing run/metadata/score → check `unavailable` → overall failed

Example (RAG portfolio uses pack metric names):

```yaml
hit_at_k:
  min: 0.8
groundedness:
  min: 0.7
correctness:
  min: 0.7
latency:
  p95_max_ms: 30000
regression:
  max_delta: -0.05   # optional mean floor; omit for bootstrap-only
  # allow_insufficient_n: true   # optional; demos with n < 5 only
# Relative bounds vs the baseline (optional):
#   latency: {p95_max_ms: 30000, max_increase_pct: 25}
#   cost: {max_increase_pct: 10}
#   experiment_metrics:
#     opengrade.error_rate: {max: 0.05, max_increase: 0.01}
```

Legacy/custom evaluator names (for example `quality` with a `contains` evaluator) remain valid when those evaluators exist on the project.

## LiveInteraction (Live runs)

Prod-like turn submitted for gold-less review (not a DatasetItem / Experiment).

Fields:
- id, project_id
- question, answer
- documents (normalized retrieval docs)
- metadata, external_id (optional; unique per project)
- judge_status: `pending` | `running` | `scored` | `error`
- metrics_set_id, score_warning, error_message
- created_at, scored_at

Related:
- **LiveInteractionScore** — per gold-less metric (`groundedness`, `answer_relevance`) outcome
- **LiveScoreReview** — per-score human verdict `agree` | `disagree` with the judge label, optional `corrected_explanation` / note (source for judge calibration)

Promote creates a DatasetItem on a chosen dataset (does not delete the live interaction).

### LiveScoreReview

Fields: `id`, `live_interaction_score_id` (unique), `verdict`, `corrected_explanation`, `note`, `reviewer`, `created_at`. Deleted when the score is replaced on rescore.

## Review

Human judgement attached to a trace/span/evaluation result (generic Phase 5 model; Live Run MVP uses LiveScoreReview).

Fields:
- id
- target_type
- target_id
- label
- score
- comment
- reviewer
- created_at

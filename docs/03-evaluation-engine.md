# Evaluation Engine

## Core interface

```python
from dataclasses import dataclass
from typing import Protocol, Any


@dataclass(frozen=True)
class EvaluationSample:
    input: Any
    expected_output: Any | None
    actual_output: Any | None
    context: Any | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class EvaluationResult:
    score: float | None
    label: str | None
    explanation: str | None
    metadata: dict[str, Any]


class Evaluator(Protocol):
    name: str

    async def evaluate(
        self,
        sample: EvaluationSample,
    ) -> EvaluationResult: ...
```

## Built-in evaluators — MVP

### Deterministic
- exact_match
- contains
- regex
- json_schema
- hit_at_k (config `k`; uses `metadata.expected_doc_ids` and run context documents / `retrieved_doc_ids`)
- latency
- token_usage
- cost
- tool_call_success

### LLM judge
- answer_relevance
- groundedness
- correctness

LLM judges must return structured output and be versioned by evaluator configuration.

## RAG metrics sets and pack scoring

Projects hold versioned **metrics sets**; the default set seeds RAG kinds (`hit_at_k`, `must_contain`, `groundedness`, `correctness`, `latency`). `POST /experiments/{experiment_id}/evaluate-pack` resolves a set (body override → experiment pin → project default), then runs all **enabled** entries with linked `evaluator_id` values against experiment item outputs (including OTLP-bound runs). Optional `save_as_default` persists the request set on the experiment.

Evaluators are shared per kind across metrics sets, so each entry's `config` (e.g. `k`, `max_ms`, judge `model`) is overlaid on the evaluator config at scoring time (`kind` cannot be overridden); run metadata records `config_override` and the effective `config_hash`. Live scoring applies the same overlay.

Output resolution: once an experiment has any recorded outputs, every item is read from those outputs only — dataset-level `actual_output`/`context` are never used as fallback (they belong to another run). Items without an output in that experiment score `FAIL` (0.0, `metadata.missing_output=true`) for every evaluator. Experiments with no outputs at all keep reading inline dataset fields (e.g. datasets built from traces).

Explicit `POST .../evaluate` with `evaluator_ids` bypasses set resolution.

Groundedness reads retrieved chunk text from run `context.documents` (populated from SDK `set_retrieval_documents` or ingestion normalization).

## Evaluator execution

```text
Dataset
   │
   ▼
Scheduler (or evaluate-pack / metrics set)
   │
   ├── evaluator A ──► results
   ├── evaluator B ──► results
   └── evaluator C ──► results
                     │
                     ▼
              Aggregation
                     │
                     ▼
                Experiment / Run
```

## Scoring

Every evaluator must document:
- score range
- higher/lower-is-better semantics
- threshold compatibility
- whether scores are deterministic
- provider/model dependency

## Reproducibility

An evaluation run stores:
- evaluator name/version
- configuration hash
- dataset version
- model/provider
- prompt/template version
- execution timestamp
- application version

## Failure handling

Do not use score=0 for infrastructure failures or non-evaluable inputs.

Use explicit states:

```text
PENDING
RUNNING
PASSED
FAILED
ERROR
SKIPPED
```

Outcome classes:

- **ERROR** — judge/infra failure (timeout, exception). `score` is null; run becomes `ERROR`.
- **SKIPPED** — metric cannot be evaluated (missing gold / required fields). `score` is null; excluded from mean/pass_rate.
- **FAIL** with minimum score (usually `0.0`) — quality miss, including empty/missing retrieval when gold is present. Lowers mean/pass_rate and can fail gates.

Helpers: `aiobs.evaluation.outcomes` (`skip`, `fail_min`, `error`, `pass_`).

## LLM judge requirements

- structured JSON output
- timeout
- retry policy
- max concurrency
- token/cost accounting
- model/provider recorded
- optional redaction
- judge prompt version recorded

## Future extension

Evaluator registry:

```python
register_evaluator("my_business_rule", MyBusinessRuleEvaluator)
```

Custom evaluators should be loadable without modifying the core engine.

This registry is a primary open-source extension surface: contributors add evaluators as packages/adapters, not by forking API or UI code.

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

## RAG metrics pack

Project-scoped pack (`hit_at_k`, `groundedness`, `correctness`, `latency` by default). `POST /experiments/{experiment_id}/evaluate-pack` runs all **enabled** pack evaluators against experiment item outputs (including OTLP-bound runs).

Groundedness reads retrieved chunk text from run `context.documents` (populated from SDK `set_retrieval_documents` or ingestion normalization).

## Evaluator execution

```text
Dataset
   │
   ▼
Scheduler (or evaluate-pack)
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

An evaluator failure must not silently become score=0.

Use explicit states:

```text
PENDING
RUNNING
PASSED
FAILED
ERROR
SKIPPED
```

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

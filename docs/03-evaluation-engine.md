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
- latency
- token_usage
- cost
- tool_call_success

### LLM judge
- answer_relevance
- groundedness
- correctness

LLM judges must return structured output and be versioned by evaluator configuration.

## Evaluator execution

```text
Dataset
   │
   ▼
Scheduler
   │
   ├── evaluator A ──► results
   ├── evaluator B ──► results
   └── evaluator C ──► results
                     │
                     ▼
              Aggregation
                     │
                     ▼
                Experiment
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

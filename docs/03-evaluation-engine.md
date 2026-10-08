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
- recall_at_k (same inputs; `|expected ∩ top-k| / |expected|`)
- mrr (same inputs; `1/rank` of first expected id in top-k, else `0`)
- latency
- token_usage
- cost
- tool_call_success

### LLM judge
- answer_relevance
- groundedness
- correctness
- context_precision

LLM judges return structured, validated output and are versioned by `prompt_version` (see [LLM judges (v3)](#llm-judges-v3)).

## RAG metrics sets and pack scoring

Projects hold versioned **metrics sets**; the default set seeds RAG kinds (`hit_at_k`, `recall_at_k`, `mrr`, `context_precision`, `must_contain`, `groundedness`, `correctness`, `latency`). `POST /experiments/{experiment_id}/evaluate-pack` resolves a set (body override → experiment pin → project default), then runs all **enabled** entries with linked `evaluator_id` values against experiment item outputs (including OTLP-bound runs). Optional `save_as_default` persists the request set on the experiment.

Evaluators are shared per kind across metrics sets, so each entry's `config` (e.g. `k`, `max_ms`, judge `model`) is overlaid on the evaluator config at scoring time (`kind` cannot be overridden); run metadata records `config_override` and the effective `config_hash`. Live scoring applies the same overlay.

Output resolution: once an experiment has any recorded outputs, every item is read from those outputs only — dataset-level `actual_output`/`context` are never used as fallback (they belong to another run). Items without an output in that experiment score `FAIL` (0.0, `metadata.missing_output=true`) for every evaluator. Experiments with no outputs at all keep reading inline dataset fields (e.g. datasets built from traces).

Explicit `POST .../evaluate` with `evaluator_ids` bypasses set resolution.

Groundedness reads retrieved chunk text from run `context.documents` (populated from SDK `set_retrieval_documents` or ingestion normalization). When a trace has several retrieval stages (`RETRIEVER` → `RERANKER`), `context.documents` comes from the last stage that recorded documents (by end time, deduplicated by id): the documents the model actually saw.

PASS/FAIL rule (offline runs and live scoring): an item passes only if the evaluator label is not `FAIL` **and** the score meets the entry threshold. The stored label is that effective verdict; when it overrides the evaluator's own label, the original is kept in `metadata.judge_label` (live: appended to the explanation). LLM judges never emit a label, so for them the verdict comes from the threshold alone. A run is `FAILED` if any item fails.

LLM judges only receive the fields their rubric needs: `answer_relevance` gets input + answer, `groundedness` adds `context.documents`, `correctness` adds `expected_output`, `context_precision` adds `expected_output` + `context.documents`. Item `metadata` (e.g. `expected_doc_ids`) is never sent to a judge. Prompt versions are `{kind}.{method}.v3`.

Live scoring: a failing judge records an `ERROR` score for its kind without discarding the others (`score_warning` lists the failed kinds; status is `error` only if every judge failed).

## LLM judges (v3)

Code: `aiobs.evaluation.judges` (`prompts`, `parsing`, `claims`, `rubric`, `evaluators`, `cache`, `warnings`). Judges return `label=None`; `explanation` is a short human-readable summary and structured details go into `metadata`.

### Methods and config

| Kind | `method` | Notes |
|---|---|---|
| `groundedness` | `claims` (default), `rubric` | claims: extract answer claims, verify each against `context.documents` (2 calls) |
| `correctness` | `claims` (default), `rubric` | claims: extract gold claims from `expected_output`, check coverage in the answer (2 calls, 4 with `scoring: f1`; one fewer on a gold-claim cache hit) |
| `answer_relevance` | `rubric` (only value) | one call, anchored 1-5 level |
| `context_precision` | `claims` (default), `rubric` | claims: one batched relevance verdict per retrieved document vs question + reference; score is RAGAS average precision |

`rubric` for groundedness/correctness is a single holistic call intended for small local models; it is never selected as a silent fallback.

Entry config keys (part of `config_hash`). Invalid values raise `ValueError` when the evaluator is built.

| key | values | default | applies to |
|---|---|---|---|
| `method` | `claims` \| `rubric` | `claims` (groundedness, correctness, context_precision), `rubric` (answer_relevance) | all judges |
| `scoring` | `recall` \| `f1` | `recall` | correctness with `method=claims` |
| `max_claims` | integer >= 1 | 30 | `method=claims`; extra claims are dropped and `claims_truncated=true` |
| `model` | LiteLLM model id | `LLM_MODEL` | all |
| `temperature` | finite float | `LLM_TEMPERATURE` | all |

### Scoring

- **Groundedness (claims):** `supported / claims`. Each claim is `supported`, `contradicted` or `not_supported`. Zero claims (refusal, "I don't know") is `SKIPPED` (`no_factual_claims`). Missing `context` is `SKIPPED`; empty `context.documents` is a minimum-score `FAIL`.
- **Correctness (claims):** recall `= covered / gold claims`; any `contradicted` gold claim gives `0.0`. `scoring: f1` adds two calls: extract the answer's own claims, then check them against `expected_output` (`precision = supported / answer claims`, score is F1, still `0.0` on any contradiction). Zero gold claims is `SKIPPED` (`no_gold_claims`). Extra non-contradicting statements are not penalized by recall.
- **Context precision (claims):** for each retrieved document (rank order), verdict `relevant` / `not_relevant` vs question + `expected_output`. Score is average precision \(\sum_k (P@k \cdot v_k) / \sum v_k\); `0` when no document is relevant. Optional `config.k` truncates the document list; `max_claims` is also applied as a safety cap. Missing `expected_output` or `context` is `SKIPPED`; empty `context.documents` is a minimum-score `FAIL`.
- **Rubric:** `{reasoning, level}` with `level` 1-5 and `score = (level - 1) / 4`.
- Missing `actual_output` is `SKIPPED` for every judge; correctness and context_precision also need `expected_output`.
- PASS/FAIL comes only from the entry threshold.

### Determinism and versioning

- `LLM_TEMPERATURE` (default `0.0`) and `LLM_SEED` (default `42`) are sent on every judge call; `LiteLlmClient` passes `drop_params=True` so providers without `seed` ignore it. Entry `temperature` / `model` override them per entry.
- `prompt_version = "{kind}.{method}.v3"` (e.g. `groundedness.claims.v3`) is stored in each result's metadata and in `run.metadata.prompt_version`. Compare flags a `prompt_version` mismatch between candidate and baseline as a config mismatch (flagged, not blocked); runs from before v3 carry none and count as a different version.
- Result metadata: `method`, `prompt_version`, `model`, `claims` (per claim `text` and `verdict`, plus `doc_ids`/`quote`/`reasoning` where applicable), counts (`n_claims`, `n_supported`, `n_contradicted`; correctness: `n_gold`, `n_covered`, `n_missing`, `recall`, and `precision` for f1), `claims_truncated`, `llm_calls`, `cache_hit`. Rubric results store `level` and `reasoning`.
- Explanations are capped at 1000 characters (claim lists are abbreviated).

### Gold-claim cache

Gold claims extracted from `expected_output` are stored in `judge_claim_cache` (migration `0011_judge_claim_cache`), keyed by a SHA-256 of question + expected output + `prompt_version` + model. A hit skips the extract call, so candidate and baseline experiments are scored against identical gold claims. Entries are written only after the extract output passed validation.

### Output validation and errors

Every step parses tolerantly (code fences, JSON wrapped in prose), validates against a schema (enum verdicts, `level` 1-5, one verdict per claim sent) and gets one repair retry in the same conversation. Failures produce an `ERROR` result with `metadata.error_type`:

- `judge_output_invalid`: the model did not follow the format after repair; `metadata.raw_output` holds the first 2000 characters.
- `llm_unavailable`: timeout, connection, rate-limit or provider 5xx after LiteLLM retries.
- `context_overflow`: context window exceeded. Documents are never truncated silently.
- `llm_error`: any other provider error.

### Unsuitable-model warning

- **Offline:** when `judge_output_invalid` items exceed 20% of evaluated items (SKIPPED and missing-output items excluded; the other error types do not count as format failures), the run gets `metadata.warnings = ["judge_model_unsuitable"]` and `metadata.warning_detail` (`model`, `method`, `failure_rate`, `message`). The remedy is `method: rubric` or a stronger judge model.
- **Live:** an interaction whose judge result is `judge_output_invalid` gets a `judge_model_unsuitable` `score_warning`. The rolling unsuitable rate is computed in the UI from the live interactions list (only evaluated judge scores count).

### Manual smoke test

`scripts/judge_smoke.py` runs the built-in judges on a fixed sample against a real model (not part of CI):

```bash
cd backend
LLM_MODEL=ollama/gemma4:e2b LLM_API_BASE=http://localhost:11434 \
  uv run python ../scripts/judge_smoke.py [--method rubric]
```

A capable model should give groundedness about 0.5, correctness about 0.5 and answer_relevance 1.0.

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

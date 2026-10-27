# Custom evaluators

There are two ways to add a metric. Pick by where the code should run.

| | SDK metric (`@opengrade.metric`) | Server evaluator (`register_evaluator`) |
| --- | --- | --- |
| Runs in | your process, during `opengrade.evaluate` / `@trace(metrics=…)` | the OpenGrade API, on `POST /experiments/{id}/evaluate` |
| Change the server? | no | yes (contribution to `opengrade_server`) |
| Usable from UI / metrics sets / re-score | listed under "Metrics computed in your code"; cannot be re-run by the server | yes |
| Good for | app-specific checks, quick iteration | reusable metrics everyone should get |

App-specific checks belong in the SDK: see [Custom metrics](../sdk/README.md#custom-metrics). The rest of this page is for contributors adding an evaluator to the server.

## The protocol

`backend/src/opengrade_server/evaluation/protocol.py`:

```python
@dataclass(frozen=True, slots=True)
class EvaluationSample:
    input: Any
    expected_output: Any | None
    actual_output: Any | None
    context: Any | None            # e.g. {"documents": [...], "latency_ms": ...}
    metadata: dict[str, Any]       # dataset item metadata


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    score: float | None            # 0..1 by convention; None when not scored
    label: str | None              # PASS | FAIL | SKIPPED | ERROR
    explanation: str | None        # shown per item in the UI
    metadata: dict[str, Any]       # JSON-serialisable, stored with the result


class Evaluator(Protocol):
    name: str
    async def evaluate(self, sample: EvaluationSample) -> EvaluationResult: ...
```

An evaluator is built by a **factory** `Callable[[dict[str, Any]], Evaluator]` that receives the evaluator's `config` (the JSON stored on the evaluator entity). A class whose `__init__` takes `config` is a valid factory.

Rules:

- **Validate config in `__init__`** and raise `ValueError` on bad input. `POST /projects/{id}/evaluators` instantiates the factory once, so bad config is rejected at creation (400), not at scoring time.
- **Missing inputs → `SKIPPED`, not `FAIL`.** Use the helpers in `evaluation/outcomes.py`: `pass_`, `fail_min`, `skip`, `error`.
- **No network or file access in deterministic evaluators.** LLM-based evaluators go through the `LlmClient` protocol (see `evaluation/judges/`) so provider, retries, timeouts and the judge cache stay in one place.
- **Never `eval`/`exec` config.** Evaluators are trusted code; their config is user data ([security rules](10-security-privacy.md#rules)).
- **Be deterministic.** The same sample and config give the same result; compare and the quality gate depend on it.

## Example: `max_length`

```python
# backend/src/opengrade_server/evaluation/deterministic.py
class MaxLengthEvaluator:
    name = "max_length"

    def __init__(self, config: dict[str, Any]) -> None:
        max_chars = config.get("max_chars")
        if not isinstance(max_chars, int) or max_chars < 1:
            raise ValueError("max_length: config.max_chars must be a positive integer")
        self._max_chars = max_chars

    async def evaluate(self, sample: EvaluationSample) -> EvaluationResult:
        if sample.actual_output is None:
            return skip("actual_output is missing")
        length = len(_stringify(sample.actual_output))
        meta = {"length": length, "max_chars": self._max_chars}
        if length <= self._max_chars:
            return pass_(f"{length} ≤ {self._max_chars} chars", metadata=meta)
        return fail_min(f"{length} > {self._max_chars} chars", metadata=meta)
```

Register it next to the built-ins:

```python
def register_deterministic_evaluators() -> None:
    ...
    register_evaluator("max_length", MaxLengthEvaluator)
```

`register_deterministic_evaluators()` (and the LLM judges in `evaluation/judges/`) run from `bootstrap_evaluators()` at API startup (`main.py`), so the new kind is available after a restart. `kind` is case-insensitive and must be unique.

## Test it

Add unit tests in `backend/tests/` (see `test_evaluation_engine.py` for the registry fixture):

```python
@pytest.mark.asyncio
async def test_max_length() -> None:
    ev = create_evaluator("max_length", {"kind": "max_length", "max_chars": 5})
    assert (await ev.evaluate(_sample(actual_output="hello"))).label == "PASS"
    assert (await ev.evaluate(_sample(actual_output="hello!"))).label == "FAIL"
    assert (await ev.evaluate(_sample(actual_output=None))).label == "SKIPPED"
    with pytest.raises(ValueError):
        create_evaluator("max_length", {"kind": "max_length"})
```

Cover PASS, FAIL, SKIPPED and bad config. Then run the backend checks:

```bash
cd backend
uv sync --all-extras --group dev
uv run ruff check src && uv run ruff format --check src
uv run mypy src/opengrade_server
uv run pytest tests/test_evaluation_engine.py -q
```

## Use it

Create an evaluator entity that points at the kind, then select it on evaluate or add it to a metrics set:

```http
POST /api/v1/projects/{project_id}/evaluators
{"name": "short_answer", "type": "deterministic", "config": {"kind": "max_length", "max_chars": 400}}
```

`type` is one of `deterministic`, `llm_judge`, `custom`. In a release policy the evaluator is referenced by its entity name:

```yaml
short_answer:
  min: 0.9
```

## Checklist for a pull request

- [ ] Evaluator class + `register_evaluator(...)` call
- [ ] Config validated in `__init__`; SKIPPED on missing inputs
- [ ] Unit tests (PASS / FAIL / SKIPPED / bad config)
- [ ] Listed in [`03-evaluation-engine.md`](03-evaluation-engine.md) with its config keys
- [ ] For an LLM judge: prompt versioned (`prompt_version` in result metadata) and covered by `scripts/judge_sanity.py`

## Limits

Server evaluators are loaded only from the `opengrade_server` package: API startup clears the registry and runs `bootstrap_evaluators()`, and there is no plugin discovery (e.g. Python entry points) yet. Until there is, an evaluator that should not live upstream belongs in the SDK as an `@opengrade.metric`.

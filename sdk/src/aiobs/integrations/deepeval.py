"""DeepEval metrics as aiobs metrics: ``metrics=[from_deepeval(AnswerRelevancyMetric())]``."""

from __future__ import annotations

import copy
import inspect
from typing import Any

from aiobs.integrations._common import (
    as_text,
    document_texts,
    import_or_explain,
    lib_version,
    llm_name,
    snake,
)
from aiobs.metrics import LocalMetric, Sample, Score

# LLMTestCase field -> Sample field that must be present for the metric to run.
_PARAM_REQUIRES = {
    "actual_output": "output",
    "expected_output": "expected",
    "retrieval_context": "documents",
}

# These succeed when score <= threshold; aiobs thresholds pass at or above.
_LOWER_IS_BETTER = frozenset(
    {"BiasMetric", "ToxicityMetric", "HallucinationMetric", "PIILeakageMetric"}
)


def _required_params(metric: Any) -> set[str]:
    params = (
        getattr(metric, "evaluation_params", None)
        or getattr(metric, "_required_params", None)
        or []
    )
    return {str(getattr(p, "value", p)) for p in params}


def from_deepeval(
    metric: Any, *, name: str | None = None, threshold: float | None = None
) -> LocalMetric:
    """Wrap a DeepEval metric; ``reason`` becomes the explanation.

    The threshold defaults to ``metric.threshold``. Library version, metric class
    and judge model go into ``config`` so compare flags a judge or version change.
    """
    deepeval = import_or_explain("deepeval", "deepeval")
    case_cls = import_or_explain("deepeval.test_case", "deepeval").LLMTestCase
    if not callable(getattr(metric, "a_measure", None)):
        raise TypeError(f"{type(metric).__name__} is not a DeepEval metric (no a_measure)")
    if type(metric).__name__ in _LOWER_IS_BETTER:
        raise ValueError(
            f"{type(metric).__name__} is lower-is-better; aiobs thresholds pass at or above "
            "the threshold, so wrap it in a custom @aiobs.metric instead"
        )
    requires = tuple(
        sorted({_PARAM_REQUIRES[p] for p in _required_params(metric) if p in _PARAM_REQUIRES})
    )
    # Keep the spinner off and never post results to Confident AI.
    measure_params = inspect.signature(metric.a_measure).parameters
    measure_kwargs: dict[str, Any] = {
        p: False for p in ("_show_indicator", "_log_metric_to_confident") if p in measure_params
    }

    async def score(sample: Sample) -> Score:
        case = case_cls(
            input="" if sample.input is None else as_text(sample.input),
            actual_output=None if sample.output is None else as_text(sample.output),
            expected_output=None if sample.expected is None else as_text(sample.expected),
            retrieval_context=document_texts(sample.documents) or None,
        )
        # DeepEval keeps score/reason on the metric instance: measure a copy per call
        # so concurrent items do not overwrite each other. Shallow on purpose: the
        # judge client inside cannot be deep-copied and is safe to share.
        run = copy.copy(metric)
        await run.a_measure(case, **measure_kwargs)
        value = getattr(run, "score", None)
        reason = getattr(run, "reason", None)
        return Score(None if value is None else float(value), explanation=reason)

    metric_name = str(getattr(metric, "__name__", "") or type(metric).__name__)
    config: dict[str, Any] = {
        "lib": "deepeval",
        "lib_version": lib_version(deepeval),
        "metric": type(metric).__name__,
    }
    model = llm_name(getattr(metric, "model", None))
    if model:
        config["llm"] = model
    if threshold is None:
        threshold = getattr(metric, "threshold", None)
    return LocalMetric(
        score, name or f"deepeval.{snake(metric_name)}", threshold, config, requires
    )

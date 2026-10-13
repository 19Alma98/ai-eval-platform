"""Ragas metrics as aiobs metrics: ``metrics=[from_ragas(Faithfulness(llm=judge))]``."""

from __future__ import annotations

from typing import Any

from aiobs.integrations._common import (
    as_text,
    document_texts,
    import_or_explain,
    lib_version,
    llm_name,
    snake,
)
from aiobs.metrics import LocalMetric, Sample

# Ragas column -> Sample field that must be present for the metric to run.
_COLUMN_REQUIRES = {
    "response": "output",
    "retrieved_contexts": "documents",
    "reference": "expected",
}


def _single_turn_columns(metric: Any) -> set[str]:
    columns = (
        getattr(metric, "required_columns", None)
        or getattr(metric, "_required_columns", None)
        or {}
    )
    for key, names in dict(columns).items():
        if "SINGLE_TURN" in str(getattr(key, "name", key)).upper():
            return {str(n) for n in names if not str(n).endswith(":optional")}
    return set()


def from_ragas(
    metric: Any, *, name: str | None = None, threshold: float | None = None
) -> LocalMetric:
    """Wrap a Ragas single-turn metric.

    The library version, metric class and judge model go into ``config``, so a
    Ragas upgrade or a judge swap shows up in compare as a config mismatch.
    """
    ragas = import_or_explain("ragas", "ragas")
    sample_cls = import_or_explain("ragas.dataset_schema", "ragas").SingleTurnSample
    if not callable(getattr(metric, "single_turn_ascore", None)):
        raise TypeError(
            f"{type(metric).__name__} is not a Ragas single-turn metric (no single_turn_ascore)"
        )
    columns = _single_turn_columns(metric)
    requires = tuple(sorted({_COLUMN_REQUIRES[c] for c in columns if c in _COLUMN_REQUIRES}))

    async def score(sample: Sample) -> float:
        ragas_sample = sample_cls(
            user_input=None if sample.input is None else as_text(sample.input),
            response=None if sample.output is None else as_text(sample.output),
            retrieved_contexts=document_texts(sample.documents) or None,
            reference=None if sample.expected is None else as_text(sample.expected),
        )
        return float(await metric.single_turn_ascore(ragas_sample))

    metric_name = str(getattr(metric, "name", "") or type(metric).__name__)
    config: dict[str, Any] = {
        "lib": "ragas",
        "lib_version": lib_version(ragas),
        "metric": type(metric).__name__,
    }
    model = llm_name(getattr(metric, "llm", None))
    if model:
        config["llm"] = model
    return LocalMetric(score, name or f"ragas.{snake(metric_name)}", threshold, config, requires)

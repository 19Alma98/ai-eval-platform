from __future__ import annotations

import asyncio
import math
from fractions import Fraction
from typing import Any

import pytest

from opengrade.metrics import LocalMetric, Sample, Score, coerce_score, evaluate_metric, metric


def test_sample_defaults_are_empty() -> None:
    sample = Sample(input="q", output="a")
    assert sample.expected is None
    assert sample.documents == [] and sample.context == {} and sample.metadata == {}
    assert sample.trace_id is None and sample.item_id is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, Score()),
        (True, Score(1.0)),
        (False, Score(0.0)),
        (1, Score(1.0)),
        (0.25, Score(0.25)),
        ({"score": 0.5}, Score(0.5)),
        (
            {"score": True, "label": "pass", "explanation": "ok", "metadata": {"k": 1}},
            Score(1.0, label="PASS", explanation="ok", metadata={"k": 1}),
        ),
        (Score(0.3, label="fail"), Score(0.3, label="FAIL")),
        (
            {"score": Score(0.3, label="FAIL", explanation="x", metadata={"k": 1})},
            Score(0.3, label="FAIL", explanation="x", metadata={"k": 1}),
        ),
        (Fraction(1, 4), Score(0.25)),
    ],
)
def test_coerce_score_accepts_supported_returns(raw: object, expected: Score) -> None:
    assert coerce_score(raw) == expected


@pytest.mark.parametrize("raw", ["0.5", [0.5], {"value": 0.5}, object()])
def test_coerce_score_rejects_other_types(raw: object) -> None:
    with pytest.raises(TypeError, match="metric must return"):
        coerce_score(raw)


@pytest.mark.parametrize("raw", [math.nan, math.inf, {"score": -math.inf}, Score(math.nan)])
def test_coerce_score_rejects_non_finite(raw: object) -> None:
    with pytest.raises(ValueError, match="finite"):
        coerce_score(raw)


def test_coerce_score_rejects_unknown_label() -> None:
    with pytest.raises(ValueError, match="label"):
        coerce_score(Score(1.0, label="MAYBE"))


def test_decorator_without_parentheses_keeps_function_callable() -> None:
    @metric
    def exact(sample: Sample) -> bool:
        return bool(sample.output == sample.expected)

    assert isinstance(exact, LocalMetric)
    assert exact.name == "exact"
    assert exact.threshold is None and dict(exact.config) == {} and exact.requires == ()
    assert exact(Sample(output="a", expected="a")) is True


def test_decorator_options_and_version_in_config() -> None:
    @metric(name="cites", threshold=0.5, version=2, config={"k": 3}, requires=["documents"])
    def cites_source(sample: Sample) -> float:
        return 1.0

    assert cites_source.name == "cites"
    assert cites_source.threshold == 0.5
    assert dict(cites_source.config) == {"k": 3, "version": 2}
    assert cites_source.requires == ("documents",)


def test_lambda_gets_no_name() -> None:
    assert metric(lambda s: 1.0).name is None


def test_unknown_requirement_rejected() -> None:
    with pytest.raises(ValueError, match="unknown requires"):
        LocalMetric(lambda s: 1.0, requires=("gold",))


def test_evaluate_metric_sample_signature() -> None:
    m = LocalMetric(lambda s: len(s.documents))
    assert evaluate_metric(m, Sample(documents=[{"id": "d1"}])) == Score(1.0)


def test_evaluate_metric_item_output_signature_gets_item() -> None:
    seen: list[Any] = []

    def legacy(item: Any, output: Any) -> float:
        seen.append(item)
        return 0.5

    item = object()
    assert evaluate_metric(LocalMetric(legacy), Sample(output="x"), item=item) == Score(0.5)
    assert seen == [item]


def test_evaluate_metric_item_output_signature_without_item_gets_sample() -> None:
    sample = Sample(input="q", output="x")
    assert evaluate_metric(LocalMetric(lambda item, out: item is sample), sample) == Score(1.0)


def test_evaluate_metric_async() -> None:
    async def slow(sample: Sample) -> Score:
        await asyncio.sleep(0)
        return Score(0.75, explanation="async")

    assert evaluate_metric(LocalMetric(slow), Sample()) == Score(0.75, explanation="async")


@pytest.mark.parametrize(
    ("requires", "sample", "missing"),
    [
        (("expected",), Sample(output="a"), "expected"),
        (("documents",), Sample(output="a", documents=[]), "documents"),
        (("output",), Sample(output=""), "output"),
        (("context",), Sample(output="a"), "context"),
    ],
)
def test_missing_requirement_is_skipped_without_calling(
    requires: tuple[str, ...], sample: Sample, missing: str
) -> None:
    def never(sample: Sample) -> float:
        raise AssertionError("must not be called")

    result = evaluate_metric(LocalMetric(never, requires=requires), sample)
    assert result == Score(label="SKIPPED", explanation=f"missing {missing}")


def test_metric_exceptions_propagate() -> None:
    def broken(sample: Sample) -> float:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        evaluate_metric(LocalMetric(broken), Sample())


def test_coerce_score_normalizes_metadata_to_json() -> None:
    class Opaque:
        def __str__(self) -> str:
            return "opaque"

    score = coerce_score(Score(1.0, metadata={"pair": (1, 2), "obj": Opaque()}))
    assert score.metadata == {"pair": [1, 2], "obj": "opaque"}


@pytest.mark.parametrize("metadata", [{"x": math.nan}, {"x": math.inf}])
def test_coerce_score_rejects_non_json_metadata(metadata: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        coerce_score({"score": 1.0, "metadata": metadata})


def test_rewrapping_a_metric_keeps_its_signature_and_requirements() -> None:
    @metric(name="legacy", version=1, requires=("output",))
    def legacy(item: Any, output: Any) -> float:
        return 1.0 if item == "the-item" else 0.0

    wrapped = LocalMetric(legacy, threshold=0.5, config={"k": 3})

    assert wrapped.fn is legacy.fn
    assert wrapped.name == "legacy"
    assert wrapped.threshold == 0.5
    assert dict(wrapped.config) == {"version": 1, "k": 3}
    assert wrapped.requires == ("output",)
    assert evaluate_metric(wrapped, Sample(output="a"), item="the-item") == Score(1.0)
    assert evaluate_metric(wrapped, Sample(output="")) == Score(
        label="SKIPPED", explanation="missing output"
    )


def test_rewrapping_merges_requirements_and_outer_values_win() -> None:
    inner = LocalMetric(lambda s: 1.0, name="inner", threshold=0.2, requires=("documents",))
    outer = metric(name="outer", threshold=0.9, requires=("expected", "documents"))(inner)

    assert outer.name == "outer"
    assert outer.threshold == 0.9
    assert outer.requires == ("documents", "expected")

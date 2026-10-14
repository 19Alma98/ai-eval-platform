from __future__ import annotations

import asyncio
import enum
import sys
import types
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from aiobs.metrics import Sample, Score, evaluate_metric


class FakeParams(enum.Enum):
    INPUT = "input"
    ACTUAL_OUTPUT = "actual_output"
    EXPECTED_OUTPUT = "expected_output"
    RETRIEVAL_CONTEXT = "retrieval_context"


@dataclass
class FakeTestCase:
    input: str
    actual_output: str | None
    expected_output: str | None = None
    retrieval_context: list[str] | None = None


class FakeRelevancy:
    __name__ = "Answer Relevancy"
    _required_params = [FakeParams.INPUT, FakeParams.ACTUAL_OUTPUT, FakeParams.RETRIEVAL_CONTEXT]

    def __init__(self, threshold: float = 0.5) -> None:
        self.threshold = threshold
        self.model = SimpleNamespace(get_model_name=lambda: "judge-2")
        self.score: float | None = None
        self.reason: str | None = None
        self.cases: list[FakeTestCase] = []

    async def a_measure(self, test_case: FakeTestCase, _show_indicator: bool = True) -> float:
        assert _show_indicator is False
        self.cases.append(test_case)
        self.score = 1.0 if test_case.actual_output == "ok" else 0.0
        await asyncio.sleep(0.01)  # another item would overwrite score here without a copy
        self.reason = f"saw {test_case.actual_output}"
        return self.score


class FakeGEval:
    def __init__(self) -> None:
        self.threshold = 0.7
        self.evaluation_params = [FakeParams.ACTUAL_OUTPUT, FakeParams.EXPECTED_OUTPUT]
        self.score: float | None = None
        self.reason: str | None = None

    async def a_measure(self, test_case: FakeTestCase) -> float:
        self.score = 0.9
        self.reason = None
        return 0.9


class FakeEcho:
    def __init__(self) -> None:
        self.score: float | None = None
        self.reason: str | None = None

    async def a_measure(self, test_case: FakeTestCase) -> float:
        self.score = 1.0
        self.reason = repr(test_case.actual_output)
        return 1.0


@pytest.fixture
def fake_deepeval(monkeypatch: pytest.MonkeyPatch) -> None:
    deepeval: Any = types.ModuleType("deepeval")
    deepeval.__version__ = "1.4.0"
    test_case: Any = types.ModuleType("deepeval.test_case")
    test_case.LLMTestCase = FakeTestCase
    deepeval.test_case = test_case
    monkeypatch.setitem(sys.modules, "deepeval", deepeval)
    monkeypatch.setitem(sys.modules, "deepeval.test_case", test_case)


def test_from_deepeval_maps_case_reason_and_config(fake_deepeval: None) -> None:
    from aiobs.integrations.deepeval import from_deepeval

    original = FakeRelevancy()
    m = from_deepeval(original)

    assert m.name == "deepeval.answer_relevancy"
    assert m.threshold == 0.5
    assert m.requires == ("documents", "output")
    assert dict(m.config) == {
        "lib": "deepeval",
        "lib_version": "1.4.0",
        "metric": "FakeRelevancy",
        "llm": "judge-2",
    }

    result = evaluate_metric(m, Sample(input="q", output="ok", documents=[{"text": "d1"}]))
    assert result == Score(1.0, explanation="saw ok")
    assert original.cases == [FakeTestCase(input="q", actual_output="ok", retrieval_context=["d1"])]
    assert original.score is None  # measured on a copy


def test_threshold_override_and_evaluation_params(fake_deepeval: None) -> None:
    from aiobs.integrations.deepeval import from_deepeval

    m = from_deepeval(FakeGEval(), name="tone", threshold=0.8)
    assert m.name == "tone"
    assert m.threshold == 0.8
    assert m.requires == ("expected", "output")
    assert evaluate_metric(m, Sample(input="q", output="a", expected="a")) == Score(0.9)


def test_concurrent_items_do_not_share_state(fake_deepeval: None) -> None:
    from aiobs.integrations.deepeval import from_deepeval

    m = from_deepeval(FakeRelevancy())
    samples = [
        Sample(input=str(i), output="ok" if i % 2 else "bad", documents=[{"text": "d"}])
        for i in range(8)
    ]
    with ThreadPoolExecutor(max_workers=8) as pool:
        scores = list(pool.map(lambda s: evaluate_metric(m, s), samples))
    assert [s.value for s in scores] == [0.0, 1.0] * 4
    assert [s.explanation for s in scores] == [f"saw {s.output}" for s in samples]


def test_missing_library_explains_install(monkeypatch: pytest.MonkeyPatch) -> None:
    from aiobs.integrations.deepeval import from_deepeval

    monkeypatch.setitem(sys.modules, "deepeval", None)
    with pytest.raises(ImportError, match=r"pip install 'aiobs-eval\[deepeval\]'"):
        from_deepeval(FakeRelevancy())


def test_non_deepeval_metric_fails_fast(fake_deepeval: None) -> None:
    from aiobs.integrations.deepeval import from_deepeval

    with pytest.raises(TypeError, match="DeepEval metric"):
        from_deepeval(object())


def test_missing_output_is_none_not_null_string(fake_deepeval: None) -> None:
    from aiobs.integrations.deepeval import from_deepeval

    m = from_deepeval(FakeEcho())
    result = evaluate_metric(m, Sample(input="q"))
    assert isinstance(result, Score)
    assert result.explanation == "None"


def test_real_deepeval_case_accepts_our_fields() -> None:
    test_case = pytest.importorskip("deepeval.test_case")
    test_case.LLMTestCase(
        input="q", actual_output="a", expected_output=None, retrieval_context=["d"]
    )


class FakeLogging:
    def __init__(self) -> None:
        self.score: float | None = None
        self.reason: str | None = None

    async def a_measure(
        self,
        test_case: FakeTestCase,
        _show_indicator: bool = True,
        _log_metric_to_confident: bool = True,
    ) -> float:
        assert _show_indicator is False
        assert _log_metric_to_confident is False
        self.score = 1.0
        self.reason = f"input={test_case.input!r}"
        return 1.0


def test_disables_indicator_and_confident_logging(fake_deepeval: None) -> None:
    from aiobs.integrations.deepeval import from_deepeval

    m = from_deepeval(FakeLogging())
    assert evaluate_metric(m, Sample(input="q", output="a")) == Score(1.0, explanation="input='q'")
    # missing input is sent as "" (LLMTestCase.input is a required str)
    assert evaluate_metric(m, Sample(output="a")) == Score(1.0, explanation="input=''")


def test_lower_is_better_metrics_rejected(fake_deepeval: None) -> None:
    from aiobs.integrations.deepeval import from_deepeval

    class ToxicityMetric:
        async def a_measure(self, test_case: FakeTestCase) -> float:
            return 0.0

    with pytest.raises(ValueError, match="lower-is-better"):
        from_deepeval(ToxicityMetric())

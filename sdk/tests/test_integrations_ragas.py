from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from aiobs.metrics import Sample, Score, evaluate_metric


@dataclass
class FakeSingleTurnSample:
    user_input: str
    response: str
    retrieved_contexts: list[str] | None = None
    reference: str | None = None


class FakeFaithfulness:
    name = "faithfulness"
    required_columns = {"SINGLE_TURN": {"user_input", "response", "retrieved_contexts"}}

    def __init__(self) -> None:
        self.llm = SimpleNamespace(langchain_llm=SimpleNamespace(model_name="judge-1"))
        self.seen: list[FakeSingleTurnSample] = []

    async def single_turn_ascore(self, sample: FakeSingleTurnSample) -> float:
        self.seen.append(sample)
        return 0.75


class FakeCorrectness:
    name = "answer correctness"
    required_columns = {
        "SINGLE_TURN": {"user_input", "response", "reference", "retrieved_contexts:optional"}
    }

    async def single_turn_ascore(self, sample: FakeSingleTurnSample) -> float:
        return 1.0


@pytest.fixture
def fake_ragas(monkeypatch: pytest.MonkeyPatch) -> None:
    ragas: Any = types.ModuleType("ragas")
    ragas.__version__ = "0.2.15"
    schema: Any = types.ModuleType("ragas.dataset_schema")
    schema.SingleTurnSample = FakeSingleTurnSample
    ragas.dataset_schema = schema
    monkeypatch.setitem(sys.modules, "ragas", ragas)
    monkeypatch.setitem(sys.modules, "ragas.dataset_schema", schema)


def test_from_ragas_maps_sample_and_config(fake_ragas: None) -> None:
    from aiobs.integrations.ragas import from_ragas

    ragas_metric = FakeFaithfulness()
    m = from_ragas(ragas_metric, threshold=0.6)

    assert m.name == "ragas.faithfulness"
    assert m.threshold == 0.6
    assert m.requires == ("documents", "output")
    assert dict(m.config) == {
        "lib": "ragas",
        "lib_version": "0.2.15",
        "metric": "FakeFaithfulness",
        "llm": "judge-1",
    }

    sample = Sample(
        input="q",
        output={"a": 1},
        documents=[{"text": "d1"}, {"content": "d2"}, {"id": "x"}],
    )
    assert evaluate_metric(m, sample) == Score(0.75)
    (seen,) = ragas_metric.seen
    assert seen == FakeSingleTurnSample(
        user_input="q",
        response='{"a": 1}',
        retrieved_contexts=["d1", "d2", '{"id": "x"}'],
        reference=None,
    )


def test_optional_columns_do_not_require_and_reference_requires_expected(
    fake_ragas: None,
) -> None:
    from aiobs.integrations.ragas import from_ragas

    m = from_ragas(FakeCorrectness(), name="correct")
    assert m.name == "correct"
    assert m.requires == ("expected", "output")
    assert evaluate_metric(m, Sample(input="q", output="a")) == Score(
        label="SKIPPED", explanation="missing expected"
    )
    assert evaluate_metric(m, Sample(input="q", output="a", expected="a")) == Score(1.0)


def test_missing_library_explains_install(monkeypatch: pytest.MonkeyPatch) -> None:
    from aiobs.integrations.ragas import from_ragas

    monkeypatch.setitem(sys.modules, "ragas", None)
    with pytest.raises(ImportError, match=r"pip install 'aiobs-eval\[ragas\]'"):
        from_ragas(FakeFaithfulness())


def test_real_ragas_sample_accepts_our_fields() -> None:
    schema = pytest.importorskip("ragas.dataset_schema")
    schema.SingleTurnSample(user_input="q", response="a", retrieved_contexts=["d"], reference=None)


def test_rejects_metric_without_single_turn_scoring(fake_ragas: None) -> None:
    from aiobs.integrations.ragas import from_ragas

    with pytest.raises(TypeError, match="single-turn"):
        from_ragas(object())


def test_none_input_and_output_stay_none(fake_ragas: None) -> None:
    from aiobs.integrations.ragas import from_ragas

    class InputOnly:
        name = "input only"
        required_columns = {"SINGLE_TURN": {"user_input"}}

        def __init__(self) -> None:
            self.seen: list[FakeSingleTurnSample] = []

        async def single_turn_ascore(self, sample: FakeSingleTurnSample) -> float:
            self.seen.append(sample)
            return 1.0

    metric = InputOnly()
    m = from_ragas(metric)
    assert evaluate_metric(m, Sample(input="q")) == Score(1.0)
    (seen,) = metric.seen
    assert seen.user_input == "q"
    assert seen.response is None

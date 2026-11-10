from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from tests.support.instance import activated, init_og, make_og
from tests.support.reset import reset_scores, reset_sdk

import opengrade
from opengrade import _otel, _scores, current, feedback


@pytest.fixture(autouse=True)
def _active_og(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from opengrade import _state

    monkeypatch.setenv("OPENGRADE_PROJECT_ID", "p1")
    og = init_og(project_id="p1", instrument=False)
    _state.register_runtime(og._runtime)
    with activated(og):
        yield


TID = "ab" * 16


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[dict[str, Any]]]] = []
        self.lock = threading.Lock()

    def __call__(self, project_id: str, scores: list[dict[str, Any]]) -> None:
        with self.lock:
            self.calls.append((project_id, list(scores)))

    @property
    def scores(self) -> list[dict[str, Any]]:
        return [s for _, batch in self.calls for s in batch]


@pytest.fixture(scope="module", autouse=True)
def _tracer() -> Iterator[None]:
    reset_sdk(otel=True)
    trace.set_tracer_provider(TracerProvider())
    yield
    reset_sdk(otel=True)


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> Iterator[Recorder]:
    # An earlier test may have called set_project(); only the env var should count here.
    monkeypatch.setenv("OPENGRADE_PROJECT_ID", "p1")
    recorder = Recorder()
    reset_scores(recorder, interval=60.0)
    yield recorder
    reset_scores()


def test_log_score_explicit_trace(sent: Recorder) -> None:
    assert current().log_score(
        "quality",
        0.4,
        trace_id=TID.upper(),
        threshold=0.5,
        explanation="x" * 5000,
        metadata={"k": 1},
    )
    assert current().flush()
    assert sent.calls[0][0] == "p1"
    (score,) = sent.scores
    assert score == {
        "trace_id": TID,
        "name": "quality",
        "value": 0.4,
        "source": "sdk",
        "threshold": 0.5,
        "explanation": "x" * 4000,
        "metadata": {"k": 1},
    }


def test_log_score_uses_current_trace(sent: Recorder) -> None:
    with trace.get_tracer("t").start_as_current_span("s"):
        trace_id = opengrade.current_trace_id()
        assert current().log_score("cited", True, label="pass")
    current().flush()
    assert sent.scores[0]["trace_id"] == trace_id
    assert sent.scores[0]["value"] == 1.0 and sent.scores[0]["label"] == "PASS"


def test_log_feedback_maps_to_human_score(sent: Recorder) -> None:
    assert current().log_feedback(False, trace_id=TID, comment="wrong", user_id="u1")
    current().flush()
    assert sent.scores == [
        {
            "trace_id": TID,
            "name": "user_feedback",
            "value": 0.0,
            "source": "human",
            "explanation": "wrong",
            "author": "u1",
        }
    ]


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"name": "q", "value": 1.0}, "no active trace"),
        ({"name": "q", "value": float("nan"), "trace_id": TID}, "finite"),
        ({"name": "  ", "value": 1.0, "trace_id": TID}, "name"),
        ({"name": "q", "value": 1.0, "trace_id": "nothex"}, "trace_id"),
        ({"name": "q", "value": 1.0, "trace_id": TID, "label": "MAYBE"}, "label"),
        (
            {"name": "q", "value": 1.0, "trace_id": TID, "metadata": {"blob": "x" * 17_000}},
            "metadata",
        ),
    ],
)
def test_invalid_calls_warn_and_return_false(
    sent: Recorder, caplog: pytest.LogCaptureFixture, kwargs: dict[str, Any], match: str
) -> None:
    with caplog.at_level(logging.WARNING, logger="opengrade"):
        assert current().log_score(**kwargs) is False
    assert any(match in r.message for r in caplog.records)
    current().flush()
    assert sent.scores == []


def test_no_project_warns(
    sent: Recorder, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("OPENGRADE_PROJECT_ID")
    noproj = make_og()
    with caplog.at_level(logging.WARNING, logger="opengrade"):
        with activated(noproj):
            assert current().log_score("q", 1.0, trace_id=TID) is False
    assert any("No project" in r.message for r in caplog.records)


def test_log_score_noop_when_disabled(sent: Recorder, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENGRADE_DISABLED", "1")
    assert current().log_score("q", 1.0, trace_id=TID) is False
    assert current().log_feedback(True, trace_id=TID) is False
    current().flush()
    assert sent.scores == []


def test_score_trace_runs_metric_and_queues_result(sent: Recorder) -> None:
    @opengrade.metric(threshold=0.5)
    def short(s: opengrade.Sample) -> opengrade.Score:
        return opengrade.Score(0.2, explanation="too long", metadata={"chars": len(s.output)})

    assert current().score_trace(short, opengrade.Sample(input="q", output="abc"), trace_id=TID)
    current().flush()
    assert sent.scores == [
        {
            "trace_id": TID,
            "name": "short",
            "value": 0.2,
            "source": "sdk",
            "threshold": 0.5,
            "explanation": "too long",
            "metadata": {"chars": 3},
        }
    ]


def test_score_trace_skips_missing_requirement(sent: Recorder) -> None:
    @opengrade.metric(requires=("expected",))
    def exact(s: opengrade.Sample) -> bool:
        return bool(s.output == s.expected)

    assert current().score_trace(exact, opengrade.Sample(output="a"), trace_id=TID) is False
    current().flush()
    assert sent.scores == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": "q", "value": 10**400, "trace_id": TID},
        {"name": "q", "value": "1", "trace_id": TID},
        {"name": "q", "value": 1.0, "trace_id": TID, "label": 5},
        {"name": "q", "value": 1.0, "trace_id": TID, "threshold": float("inf")},
        {"name": "q", "value": 1.0, "trace_id": 123},
        {"name": "x" * 201, "value": 1.0, "trace_id": TID},
        {"name": "q", "value": 1.0, "trace_id": TID, "metadata": [1]},
    ],
)
def test_malformed_input_never_raises(sent: Recorder, kwargs: dict[str, Any]) -> None:
    assert current().log_score(**kwargs) is False
    current().flush()
    assert sent.scores == []


def test_feedback_truncates_author_and_normalizes_values(sent: Recorder) -> None:
    assert current().log_feedback(True, trace_id=f" {TID.upper()} ", user_id="u" * 300)
    current().flush()
    (score,) = sent.scores
    assert score["trace_id"] == TID and score["value"] == 1.0 and len(score["author"]) == 200


@pytest.mark.parametrize(
    "kwargs",
    [
        {"metadata": {"k": float("nan")}},
        {"metadata": {"k": [float("inf")]}},
        {"metadata": {"k": "\ud800"}},
        {"metadata": {"\ud800": 1}},
        {"metadata": 0},
        {"metadata": ""},
        {"explanation": "bad \ud800"},
        {"name": "q\ud800"},
    ],
)
def test_unsendable_content_is_rejected(sent: Recorder, kwargs: dict[str, Any]) -> None:
    args: dict[str, Any] = {"name": "q", "value": 1.0, "trace_id": TID, **kwargs}
    assert current().log_score(**args) is False
    current().flush()
    assert sent.scores == []


def test_feedback_rejects_surrogate_author(sent: Recorder) -> None:
    assert current().log_feedback(True, trace_id=TID, user_id="u\ud800") is False
    assert sent.scores == []


def test_queue_metric_score_validates_trace_id(sent: Recorder) -> None:
    @opengrade.metric()
    def m(s: opengrade.Sample) -> float:
        return 1.0

    assert feedback.queue_metric_score("p1", "nothex", m, opengrade.Score(1.0)) is False
    assert feedback.queue_metric_score("p1", TID.upper(), m, opengrade.Score(1.0)) is True
    current().flush()
    assert [s["trace_id"] for s in sent.scores] == [TID]


class Hostile:
    def __str__(self) -> str:
        raise RuntimeError("boom")


def test_hostile_str_in_metadata_never_raises(sent: Recorder) -> None:
    assert current().log_score("q", 1.0, trace_id=TID, metadata={"k": Hostile()}) is False
    assert current().log_score("q", 1.0, trace_id=TID, explanation=Hostile()) is False  # type: ignore[arg-type]
    assert current().log_feedback(True, trace_id=TID, user_id=Hostile()) is False  # type: ignore[arg-type]
    current().flush()
    assert sent.scores == []


def test_queue_metric_score_never_raises(sent: Recorder) -> None:
    unnamed = opengrade.LocalMetric(lambda s: 1.0)
    assert feedback.queue_metric_score("p1", TID, unnamed, opengrade.Score(1.0)) is False

    @opengrade.metric()
    def m(s: opengrade.Sample) -> float:
        return 1.0

    assert (
        feedback.queue_metric_score("p1", TID, m, opengrade.Score(1.0, metadata={"k": Hostile()}))
        is False
    )


def test_config_warnings_are_rate_limited(
    sent: Recorder, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("OPENGRADE_PROJECT_ID")
    noproj = make_og()
    with caplog.at_level(logging.DEBUG, logger="opengrade"):
        with activated(noproj):
            for _ in range(3):
                current().log_score("q", 1.0, trace_id=TID)
                current().log_score("q", 1.0)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2  # one per category
    assert len([r for r in caplog.records if r.levelno == logging.DEBUG]) >= 4


def test_numeric_types_and_feedback_value(sent: Recorder) -> None:
    from decimal import Decimal

    assert current().log_score("q", Decimal("0.5"), trace_id=TID, threshold=Decimal("0.25"))
    assert current().log_feedback(1, trace_id=TID, user_id="a")
    assert current().log_feedback("yes", trace_id=TID, user_id="b") is False  # type: ignore[arg-type]
    assert current().log_feedback(2, trace_id=TID, user_id="c") is False
    current().flush()
    assert [s["value"] for s in sent.scores] == [0.5, 1.0]
    assert sent.scores[0]["threshold"] == 0.25


def test_empty_trace_id_is_invalid_not_current(sent: Recorder) -> None:
    with trace.get_tracer("t").start_as_current_span("s"):
        assert current().log_score("q", 1.0, trace_id="") is False


def test_flush_shares_one_timeout_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[float] = []

    class SlowProvider:
        def force_flush(self, timeout_millis: int) -> bool:
            time.sleep(0.2)
            return True

    monkeypatch.setattr(_otel, "_PROVIDER", SlowProvider())
    monkeypatch.setattr(
        _scores, "flush", lambda timeout=5.0, runtime=None: seen.append(timeout) or True
    )
    assert _otel.flush(1000)
    assert 0 <= seen[0] <= 0.85

    monkeypatch.setattr(_scores, "flush", lambda timeout=5.0, runtime=None: 1 / 0)
    assert _otel.flush(1000) is False


def test_score_trace_misuse_never_raises(sent: Recorder, caplog: pytest.LogCaptureFixture) -> None:
    def plain(s: opengrade.Sample) -> float:
        return 1.0

    with caplog.at_level(logging.WARNING, logger="opengrade"):
        assert current().score_trace(plain, opengrade.Sample(), trace_id=TID) is False  # type: ignore[arg-type]
        assert current().score_trace(None, opengrade.Sample(), trace_id=TID) is False  # type: ignore[arg-type]

        @opengrade.metric()
        def ok(s: opengrade.Sample) -> float:
            return 1.0

        assert current().score_trace(ok, "not a sample", trace_id=TID) is False  # type: ignore[arg-type]
    assert len(caplog.records) == 3
    assert current().flush()
    assert sent.scores == []


def test_score_trace_with_raising_metric_queues_error(sent: Recorder) -> None:
    @opengrade.metric()
    def broken(s: opengrade.Sample) -> float:
        raise RuntimeError("boom")

    assert current().score_trace(broken, opengrade.Sample(output="x"), trace_id=TID) is True
    assert current().flush()
    assert len(sent.scores) == 1
    score = sent.scores[0]
    assert score["name"] == "broken"
    assert score["label"] == "ERROR"
    assert score["value"] is None
    assert "RuntimeError" in score["explanation"]
    assert "boom" in score["explanation"]


def test_score_trace_from_sample(sent: Recorder) -> None:
    @opengrade.metric()
    def ok(s: opengrade.Sample) -> float:
        return 1.0

    assert current().score_trace(ok, opengrade.Sample(output="x", trace_id=TID.upper()))
    current().flush()
    assert sent.scores[0]["trace_id"] == TID


def test_feedback_without_user_id_has_no_author(sent: Recorder) -> None:
    assert current().log_feedback(True, trace_id=TID)
    current().flush()
    assert "author" not in sent.scores[0]

from __future__ import annotations

import uuid
from typing import Any

import pytest

from aiobs_server.domain.trace_score import (
    TraceScore,
    normalize_trace_id,
    summarize_trace_scores,
    trace_score_is_failed,
)

PROJECT = uuid.uuid4()
TID = "AB" * 16


def test_create_normalizes_fields() -> None:
    score = TraceScore.create(
        PROJECT,
        f"  {TID} ",
        "  quality ",
        value=1,
        label="pass",
        threshold=0.5,
        source="human",
        author="  u1 ",
        metadata={"k": 1},
    )
    assert score.trace_id == "ab" * 16
    assert score.name == "quality"
    assert score.value == 1.0 and isinstance(score.value, float)
    assert score.label == "PASS"
    assert score.threshold == 0.5
    assert score.author == "u1"
    assert score.key == (PROJECT, "ab" * 16, "quality", "human", "u1")


def test_blank_author_and_label_become_none() -> None:
    score = TraceScore.create(PROJECT, TID, "q", label="  ", author="   ")
    assert score.label is None and score.author is None
    assert score.key[-1] == ""


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"trace_id": "xyz"}, "trace_id"),
        ({"trace_id": "a" * 31}, "trace_id"),
        ({"name": "  "}, "name"),
        ({"name": "x" * 201}, "name"),
        ({"source": "bot"}, "source"),
        ({"label": "MAYBE"}, "label"),
        ({"value": float("nan")}, "value"),
        ({"value": True}, "value"),
        ({"threshold": float("inf")}, "threshold"),
    ],
)
def test_create_rejects(kwargs: dict[str, Any], match: str) -> None:
    base: dict[str, Any] = {"trace_id": TID, "name": "q"}
    base.update(kwargs)
    trace_id, name = base.pop("trace_id"), base.pop("name")
    with pytest.raises(ValueError, match=match):
        TraceScore.create(PROJECT, trace_id, name, **base)


def test_normalize_trace_id() -> None:
    assert normalize_trace_id(" " + "F" * 32) == "f" * 32


def test_summarize_groups_by_name_and_source() -> None:
    rows = [
        TraceScore.create(PROJECT, TID, "quality", value=1.0, label="PASS"),
        TraceScore.create(PROJECT, "cd" * 16, "quality", value=0.0, label="FAIL"),
        TraceScore.create(PROJECT, "ef" * 16, "quality", value=None, label="ERROR"),
        TraceScore.create(PROJECT, TID, "user_feedback", value=1.0, source="human", author="u"),
    ]
    summary = summarize_trace_scores(rows)
    assert [(r.name, r.source, r.count, r.mean, r.pass_rate) for r in summary] == [
        ("quality", "sdk", 3, 0.5, 0.5),
        ("user_feedback", "human", 1, 1.0, None),
    ]


def test_trace_score_is_failed() -> None:
    assert trace_score_is_failed(TraceScore.create(PROJECT, TID, "q", label="FAIL"))
    assert not trace_score_is_failed(TraceScore.create(PROJECT, TID, "q", label="ERROR"))
    assert not trace_score_is_failed(TraceScore.create(PROJECT, TID, "q"))

from __future__ import annotations

import uuid
from typing import Any

import pytest

from aiobs_server.domain.experiment import Experiment
from aiobs_server.domain.experiment_metric import validate_experiment_metrics


def test_validate_accepts_numbers_and_key_charset() -> None:
    assert validate_experiment_metrics({"cost_usd": 1, "a.b/c-d_E9": 0.5}) == {
        "cost_usd": 1.0,
        "a.b/c-d_E9": 0.5,
    }


def test_validate_accepts_max_length_key() -> None:
    assert validate_experiment_metrics({"x" * 200: 1.0}) == {"x" * 200: 1.0}


@pytest.mark.parametrize(
    ("metrics", "match"),
    [
        ({}, "must not be empty"),
        ({"has space": 1.0}, "invalid metric key"),
        ({"x" * 201: 1.0}, "invalid metric key"),
        ({"": 1.0}, "invalid metric key"),
        ({"ok": True}, "must be a number"),
        ({"ok": "1"}, "must be a number"),
        ({"ok": None}, "must be a number"),
        ({"ok": float("nan")}, "finite"),
        ({"ok": float("inf")}, "finite"),
        ({"ok": 10**400}, "finite"),
        ({"a\n": 1.0}, "invalid metric key"),
    ],
)
def test_validate_rejects(metrics: dict[str, Any], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        validate_experiment_metrics(metrics)


def test_with_model_config_returns_updated_copy() -> None:
    exp = Experiment.create(uuid.uuid4(), "e", uuid.uuid4(), model_config={"a": 1})
    updated = exp.with_model_config({"a": 2, "b": 3})
    assert updated.model_config == {"a": 2, "b": 3}
    assert updated.id == exp.id
    assert exp.model_config == {"a": 1}

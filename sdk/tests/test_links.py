from __future__ import annotations

import pytest

from opengrade._links import experiment_item_url, experiment_url, trace_url, ui_base_url


def test_links_match_ui_routes() -> None:
    base = "http://localhost:8000/"
    assert experiment_url(base, "e1", "p1") == "http://localhost:8000/experiments/e1?project=p1"
    assert (
        experiment_item_url(base, "e1", "i/1", "p1")
        == "http://localhost:8000/experiments/e1?item=i%2F1&project=p1"
    )
    assert trace_url(base, "ab" * 16, None) == f"http://localhost:8000/traces/{'ab' * 16}"


def test_ui_url_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENGRADE_UI_URL", "https://evals.example.com/")
    assert ui_base_url("http://api:8000") == "https://evals.example.com"

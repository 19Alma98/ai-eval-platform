"""opengrade.LlmJudge: config, register (reuse / new version), evaluate wiring, preview."""

from __future__ import annotations

import json
from typing import Any

import httpx2
import pytest

import opengrade
from opengrade import Client, LlmJudge
from opengrade.experiment import _resolve_metrics_set, _split_metrics


class _Server:
    """Minimal fake of the evaluator / metrics-set endpoints."""

    def __init__(self, evaluators: list[dict[str, Any]] | None = None) -> None:
        self.evaluators = list(evaluators or [])
        self.metrics_sets: list[dict[str, Any]] = []
        self.requests: list[tuple[str, str, Any]] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content) if request.content else None
        path = request.url.path
        self.requests.append((request.method, path, body))
        if path == "/api/v1/projects/p1/evaluators" and request.method == "GET":
            return httpx2.Response(200, json=self.evaluators)
        if path == "/api/v1/projects/p1/evaluators" and request.method == "POST":
            created = {"id": f"ev-{len(self.evaluators) + 1}", "project_id": "p1", **body}
            self.evaluators.append(created)
            return httpx2.Response(201, json=created)
        if path == "/api/v1/projects/p1/evaluators/preview":
            return httpx2.Response(
                200,
                json={
                    "score": 0.25,
                    "label": None,
                    "explanation": "level 2/5: casual",
                    "metadata": {"level": 2},
                    "system_prompt": "STEP: custom_judge_rubric ...",
                },
            )
        if path == "/api/v1/projects/p1/metrics-sets" and request.method == "GET":
            return httpx2.Response(200, json=self.metrics_sets)
        if path == "/api/v1/projects/p1/metrics-sets" and request.method == "POST":
            created = {"id": "ms-1", "project_id": "p1", **body}
            self.metrics_sets.append(created)
            return httpx2.Response(201, json=created)
        return httpx2.Response(404, json={"detail": f"unexpected {request.method} {path}"})


def _client(server: _Server) -> Client:
    return Client("http://test", transport=httpx2.MockTransport(server))


def test_exported() -> None:
    assert "LlmJudge" in opengrade.__all__
    assert opengrade.LlmJudge is LlmJudge


def test_config_shape_and_validation() -> None:
    judge = LlmJudge(
        "tone",
        criteria="  Polite and professional.  ",
        scale="binary",
        fields=("output", "input"),
        live=True,
        threshold=0.5,
        model="gpt-x",
    )
    assert judge.config() == {
        "kind": "custom_judge",
        "criteria": "Polite and professional.",
        "scale": "binary",
        "fields": ["input", "output"],
        "live": True,
        "threshold": 0.5,
        "model": "gpt-x",
    }
    levels = LlmJudge("t", criteria="c", levels={5: "great", 1: "bad"}).config()["levels"]
    assert levels == {"1": "bad", "5": "great"}
    with pytest.raises(ValueError, match="criteria"):
        LlmJudge("t", criteria=" ")
    with pytest.raises(ValueError, match="include 'output'"):
        LlmJudge("t", criteria="c", fields=("input",))
    with pytest.raises(ValueError, match="unknown fields"):
        LlmJudge("t", criteria="c", fields=("output", "tools"))
    with pytest.raises(ValueError, match="live"):
        LlmJudge("t", criteria="c", fields=("output", "expected"), live=True)
    with pytest.raises(ValueError, match="threshold"):
        LlmJudge("t", criteria="c", threshold=3)


def test_register_reuses_same_config_and_versions_changes() -> None:
    judge = LlmJudge("tone", criteria="Polite.")
    server = _Server(
        [
            {
                "id": "old",
                "name": "tone",
                "type": "llm_judge",
                "version": 1,
                "config": LlmJudge("tone", criteria="Old criteria.").config(),
            },
            {
                "id": "same",
                "name": "tone",
                "type": "llm_judge",
                "version": 2,
                "config": judge.config(),
            },
        ]
    )
    with _client(server) as client:
        assert judge.register(client, "p1").id == "same"
        changed = LlmJudge("tone", criteria="Polite and brief.").register(client, "p1")
    assert changed.version == 3
    post = [r for r in server.requests if r[0] == "POST"]
    assert post == [
        (
            "POST",
            "/api/v1/projects/p1/evaluators",
            {
                "name": "tone",
                "type": "llm_judge",
                "config": LlmJudge("tone", criteria="Polite and brief.").config(),
                "version": 3,
            },
        )
    ]


def test_evaluate_metrics_list_wires_judge_into_metrics_set() -> None:
    judge = LlmJudge("tone", criteria="Polite.", threshold=0.75)
    server_entries, local = _split_metrics(["groundedness", judge])
    assert local == []
    assert [e["kind"] for e in server_entries] == ["groundedness", "tone"]
    server = _Server()
    with _client(server) as client:
        assert _resolve_metrics_set(client, "p1", server_entries) == "ms-1"
    entries = server.metrics_sets[0]["entries"]
    assert entries[1] == {
        "kind": "tone",
        "enabled": True,
        "threshold": 0.75,
        "config": {},
        "evaluator_id": "ev-1",
    }
    assert entries[0]["kind"] == "groundedness"
    with pytest.raises(ValueError, match="duplicate metric kinds"):
        _split_metrics([judge, "tone"])


def test_preview_sends_config_and_sample() -> None:
    server = _Server()
    judge = LlmJudge("tone", criteria="Polite.")
    with _client(server) as client:
        result = judge.preview(output="yo", input="Hi?", client=client, project_id="p1")
    assert result.score == 0.25
    assert result.system_prompt is not None
    method, path, body = server.requests[-1]
    assert (method, path) == ("POST", "/api/v1/projects/p1/evaluators/preview")
    assert body["config"] == judge.config()
    assert body["sample"]["output"] == "yo"
    assert body["sample"]["input"] == "Hi?"

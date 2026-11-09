from __future__ import annotations

import json
from typing import Any

import httpx2
import pytest

import opengrade
from opengrade import Client, OpengradeAPIError
from opengrade.client import Client as ClientDirect


@pytest.fixture
def captured_requests() -> list[httpx2.Request]:
    return []


@pytest.fixture
def mock_transport(captured_requests: list[httpx2.Request]) -> httpx2.MockTransport:
    def handler(request: httpx2.Request) -> httpx2.Response:
        captured_requests.append(request)
        method = request.method
        url = str(request.url)

        if method == "GET" and url.endswith("/health"):
            return httpx2.Response(200, json={"status": "ok"})
        if method == "POST" and url.endswith("/api/v1/projects"):
            return httpx2.Response(
                201,
                json={
                    "id": "proj-1",
                    "name": "Demo",
                    "slug": "demo",
                    "created_at": "2026-01-01T00:00:00+00:00",
                },
            )
        if method == "GET" and url.rstrip("/").endswith("/api/v1/projects"):
            return httpx2.Response(200, json=[])
        if method == "POST" and url.endswith("/datasets"):
            return httpx2.Response(
                201,
                json={
                    "id": "ds-1",
                    "project_id": "proj-1",
                    "name": "gold",
                    "version": 1,
                    "task_type": "rag_qa",
                    "created_at": "2026-01-01T00:00:00+00:00",
                },
            )
        if method == "POST" and url.endswith("/items"):
            body = json.loads(request.content.decode()) if request.content else {}
            return httpx2.Response(
                201,
                json={"id": "item-1", "dataset_id": "ds-1", "input": body.get("input")},
            )
        if method == "GET" and "/datasets/ds-1" in url and "/items" not in url:
            return httpx2.Response(
                200,
                json={
                    "id": "ds-1",
                    "project_id": "proj-1",
                    "name": "gold",
                    "version": 1,
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "items": [{"id": "item-1", "input": "Q?"}],
                },
            )
        if method == "POST" and "/items/import" in url:
            return httpx2.Response(200, json={"created": 1, "errors": []})
        if method == "POST" and url.endswith("/experiments"):
            return httpx2.Response(
                201,
                json={
                    "id": "exp-1",
                    "name": "run",
                    "dataset_id": "ds-1",
                    "status": "created",
                },
            )
        if method == "GET" and url.endswith("/outputs"):
            return httpx2.Response(200, json=[])
        if method == "POST" and url.endswith("/evaluate-pack"):
            return httpx2.Response(
                202,
                json={
                    "id": "exp-1",
                    "name": "run",
                    "status": "running",
                    "dataset_id": "ds-1",
                },
            )
        if method == "GET" and url.rstrip("/").endswith("/api/v1/experiments/exp-1"):
            return httpx2.Response(
                200,
                json={
                    "id": "exp-1",
                    "name": "run",
                    "status": "completed",
                    "dataset_id": "ds-1",
                },
            )
        if method == "GET" and url.endswith("/experiments/exp-1/runs"):
            return httpx2.Response(
                200,
                json=[{"id": "run-1", "status": "PASSED", "results": []}],
            )
        if method == "GET" and "/evaluation-runs/run-1" in url:
            return httpx2.Response(
                200,
                json={"id": "run-1", "status": "PASSED", "results": []},
            )
        if method == "GET" and url.endswith("/summary"):
            return httpx2.Response(200, json={"experiment_id": "exp-1", "evaluators": []})
        if method == "GET" and "/compare/" in url:
            return httpx2.Response(
                200,
                json={
                    "experiment_id": "exp-1",
                    "baseline_experiment_id": "exp-0",
                    "metrics": [],
                    "regressions": [],
                    "improved": [],
                    "unchanged": [],
                },
            )
        if method == "POST" and url.endswith("/metrics-pack/ensure"):
            return httpx2.Response(200, json={"entries": [{"kind": "hit_at_k"}]})
        if method == "POST" and url.endswith("/projects/proj-1/live-interactions"):
            body = json.loads(request.content.decode()) if request.content else {}
            return httpx2.Response(
                202,
                json={
                    "id": "live-1",
                    "judge_status": "pending",
                    "question": body.get("question"),
                    "answer": body.get("answer"),
                },
            )
        if method == "GET" and "/projects/proj-1/live-interactions" in url:
            return httpx2.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "live-1",
                            "question": "What is PTO?",
                            "answer": "Paid time off",
                            "judge_status": "scored",
                            "scores": [{"kind": "groundedness", "score": 1.0, "label": "PASS"}],
                        }
                    ],
                    "judge_warnings": [],
                },
            )
        if method == "GET" and url.endswith("/live-interactions/live-1"):
            return httpx2.Response(
                200,
                json={
                    "id": "live-1",
                    "question": "What is PTO?",
                    "answer": "Paid time off",
                    "judge_status": "scored",
                    "scores": [{"kind": "groundedness", "score": 1.0, "label": "PASS"}],
                },
            )
        if method == "POST" and url.endswith("/live-interactions/live-1/promote"):
            body = json.loads(request.content.decode()) if request.content else {}
            return httpx2.Response(
                201,
                json={
                    "id": "item-live",
                    "dataset_id": body.get("dataset_id"),
                    "input": "What is PTO?",
                    "expected_output": body.get("expected_output"),
                    "metadata": {"expected_doc_ids": body.get("expected_doc_ids") or []},
                },
            )
        if method == "POST" and url.endswith("/live-interactions/live-1/rescore"):
            return httpx2.Response(
                200,
                json={
                    "id": "live-1",
                    "question": "What is PTO?",
                    "answer": "Paid time off",
                    "judge_status": "scored",
                    "scores": [{"kind": "groundedness", "score": 0.9, "label": "PASS"}],
                },
            )
        raise AssertionError(f"unexpected request: {method} {url}")

    return httpx2.MockTransport(handler)


def test_public_exports() -> None:
    assert "Client" in opengrade.__all__
    assert "AsyncClient" in opengrade.__all__
    assert "OpengradeAPIError" in opengrade.__all__
    assert Client is ClientDirect
    assert issubclass(OpengradeAPIError, opengrade.OpengradeError)


def test_health_and_projects(
    mock_transport: httpx2.MockTransport,
    captured_requests: list[httpx2.Request],
) -> None:
    with Client("http://localhost:8000/", transport=mock_transport) as client:
        assert client.health().status == "ok"
        project = client.projects.create(name="Demo", slug="demo")
        assert project.id == "proj-1"
        assert captured_requests[1].method == "POST"
        body: dict[str, Any] = json.loads(captured_requests[1].content.decode())
        assert body == {"name": "Demo", "slug": "demo"}
        assert client.projects.list() == []


def test_create_with_items_and_import(
    mock_transport: httpx2.MockTransport,
    captured_requests: list[httpx2.Request],
) -> None:
    with Client("http://localhost:8000", transport=mock_transport) as client:
        ds = client.datasets.create_with_items(
            "proj-1",
            name="gold",
            items=[
                {
                    "input": "Q?",
                    "expected_output": "A",
                    "metadata": {"expected_doc_ids": ["d1"]},
                }
            ],
        )
        assert ds.id == "ds-1"
        methods = [r.method for r in captured_requests]
        assert methods == ["POST", "POST"]
        assert str(captured_requests[0].url).endswith("/projects/proj-1/datasets")
        assert str(captured_requests[1].url).endswith("/datasets/ds-1/items")
        item_body = json.loads(captured_requests[1].content.decode())
        assert item_body["input"] == "Q?"
        assert item_body["metadata"]["expected_doc_ids"] == ["d1"]

        detail = client.datasets.get("ds-1")
        assert len(detail.items) == 1

        imported = client.datasets.import_items(
            "ds-1",
            file=("gold.csv", b"question,expected_answer\nQ?,A\n"),
            format="csv",
        )
        assert imported.created == 1
        last = captured_requests[-1]
        assert "format=csv" in str(last.url)
        assert "/items/import" in str(last.url)
        assert b"gold.csv" in last.content


def test_experiments_and_metrics_pack(
    mock_transport: httpx2.MockTransport,
    captured_requests: list[httpx2.Request],
) -> None:
    with Client(timeout=120.0, transport=mock_transport) as client:
        pack = client.metrics_packs.ensure("proj-1")
        assert pack.entries[0].kind == "hit_at_k"

        exp = client.experiments.create(
            "proj-1",
            name="baseline",
            dataset_id="ds-1",
            model_config={"model": "m"},
            version="v1",
            baseline_experiment_id="exp-0",
        )
        assert exp.id == "exp-1"
        body = json.loads(captured_requests[-1].content.decode())
        assert body["baseline_experiment_id"] == "exp-0"
        assert body["model_config"] == {"model": "m"}

        assert client.experiments.list_outputs("exp-1") == []
        evaluated = client.experiments.evaluate_pack("exp-1")
        assert evaluated.experiment.status == "completed"
        assert len(evaluated.runs) == 1
        assert evaluated.runs[0].status == "PASSED"
        assert client.experiments.summary("exp-1").experiment_id == "exp-1"
        compared = client.experiments.compare("exp-1", "exp-0")
        assert compared.experiment_id == "exp-1"
        assert compared.baseline_experiment_id == "exp-0"


def test_live_runs_submit(
    mock_transport: httpx2.MockTransport,
    captured_requests: list[httpx2.Request],
) -> None:
    with Client("http://localhost:8000", transport=mock_transport) as client:
        result = client.live_runs.submit(
            "proj-1",
            question="What is PTO?",
            answer="Paid time off",
            documents=[{"id": "d1", "text": "PTO means paid time off"}],
            external_id="turn-1",
            metadata={"app": "hr"},
        )
        assert result.id == "live-1"
        assert result.judge_status == "pending"
        last = captured_requests[-1]
        assert last.method == "POST"
        assert str(last.url).endswith("/projects/proj-1/live-interactions")
        body = json.loads(last.content.decode())
        assert body["question"] == "What is PTO?"
        assert body["documents"][0]["id"] == "d1"
        assert body["external_id"] == "turn-1"


def test_live_runs_list_get_promote_rescore(
    mock_transport: httpx2.MockTransport,
    captured_requests: list[httpx2.Request],
) -> None:
    with Client("http://localhost:8000", transport=mock_transport) as client:
        listed = client.live_runs.list("proj-1", failed_only=True, search="PTO", limit=10)
        assert len(listed.items) == 1
        assert listed.items[0].id == "live-1"
        list_req = captured_requests[-1]
        assert list_req.method == "GET"
        assert "failed_only=true" in str(list_req.url)
        assert "search=PTO" in str(list_req.url)

        detail = client.live_runs.get("live-1")
        assert detail.judge_status == "scored"
        assert detail.scores[0].kind == "groundedness"

        promoted = client.live_runs.promote(
            "live-1",
            dataset_id="ds-1",
            expected_output="Paid time off",
            expected_doc_ids=["d1"],
        )
        assert promoted.id == "item-live"
        assert promoted.expected_output == "Paid time off"
        promote_body = json.loads(captured_requests[-1].content.decode())
        assert promote_body["dataset_id"] == "ds-1"
        assert promote_body["expected_doc_ids"] == ["d1"]

        rescored = client.live_runs.rescore("live-1")
        assert rescored.scores[0].score == 0.9
        assert captured_requests[-1].method == "POST"
        assert str(captured_requests[-1].url).endswith("/live-interactions/live-1/rescore")


def test_alerts_resource_sends_only_set_fields() -> None:
    seen: list[tuple[str, str, Any]] = []
    rule = {"id": "r1", "name": "p99", "metric": "latency_p99_ms", "threshold": 3000}

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, request.url.path, body))
        if request.method == "DELETE":
            return httpx2.Response(204)
        return httpx2.Response(200, json=rule)

    with Client("http://test", transport=httpx2.MockTransport(handler)) as client:
        created = client.alerts.create("p1", name="p99", metric="latency_p99_ms", threshold=3000)
        client.alerts.update("r1", webhook_url=None)
        client.alerts.delete("r1")
        with pytest.raises(ValueError, match="unknown alert rule fields"):
            client.alerts.update("r1", nope=1)
    assert created.metric == "latency_p99_ms"
    assert seen[0] == (
        "POST",
        "/api/v1/projects/p1/alert-rules",
        {
            "name": "p99",
            "metric": "latency_p99_ms",
            "operator": "gt",
            "threshold": 3000,
            "window_minutes": 60,
            "webhook_format": "json",
            "enabled": True,
            "condition": "threshold",
        },
    )
    assert seen[1] == ("PATCH", "/api/v1/alert-rules/r1", {"webhook_url": None})
    assert seen[2][0] == "DELETE"


def test_live_interaction_exposes_trace_scores() -> None:
    from opengrade.models import LiveInteractionResponse

    live = LiveInteractionResponse.model_validate(
        {
            "id": "live-1",
            "question": "Who is the CEO?",
            "answer": "I don't know.",
            "judge_status": "unsampled",
            "trace_scores": [
                {
                    "id": "s-1",
                    "trace_id": "ab" * 16,
                    "name": "user_feedback",
                    "value": 0.0,
                    "label": "FAIL",
                    "explanation": "I needed a real answer",
                    "threshold": None,
                    "source": "human",
                    "author": "u-03",
                    "metadata": {},
                    "created_at": "2026-11-03T11:15:51Z",
                    "updated_at": "2026-11-03T11:15:51Z",
                }
            ],
        }
    )
    (score,) = live.trace_scores
    assert (score.name, score.value, score.label, score.author) == (
        "user_feedback",
        0.0,
        "FAIL",
        "u-03",
    )
    assert (
        LiveInteractionResponse.model_validate(
            {"id": "x", "question": "q", "answer": "a", "judge_status": "pending"}
        ).trace_scores
        == []
    )


def test_bound_client_ignores_global_active_project() -> None:
    from opengrade import _context, _state

    _context._reset_for_tests()
    _state._set_active_project(project_id="global-p", project_slug="global")
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.url.path)
        return httpx2.Response(200, json=[])

    client = Client("http://test", project_id="bound-p", transport=httpx2.MockTransport(handler))
    client.datasets.list()
    assert seen == ["/api/v1/projects/bound-p/datasets"]
    _context._reset_for_tests()


def test_two_clients_use_distinct_bound_projects() -> None:
    from opengrade import _context

    _context._reset_for_tests()
    seen: dict[str, list[str]] = {"a": [], "b": []}

    def handler_a(request: httpx2.Request) -> httpx2.Response:
        seen["a"].append(request.url.path)
        return httpx2.Response(200, json=[])

    def handler_b(request: httpx2.Request) -> httpx2.Response:
        seen["b"].append(request.url.path)
        return httpx2.Response(200, json=[])

    client_a = Client("http://test", project_id="proj-a", transport=httpx2.MockTransport(handler_a))
    client_b = Client("http://test", project_id="proj-b", transport=httpx2.MockTransport(handler_b))
    client_a.experiments.list()
    client_b.experiments.list()
    assert seen["a"] == ["/api/v1/projects/proj-a/experiments"]
    assert seen["b"] == ["/api/v1/projects/proj-b/experiments"]
    _context._reset_for_tests()


def test_set_project_refreshes_shared_client_bound_project() -> None:
    from opengrade import _context

    _context._reset_for_tests()
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path.rstrip("/")
        seen.append(path)
        if request.method == "GET" and path == "/api/v1/projects":
            return httpx2.Response(
                200,
                json=[
                    {
                        "id": "p-shared",
                        "name": "shared",
                        "slug": "shared",
                        "created_at": "2026-01-01T00:00:00+00:00",
                    }
                ],
            )
        return httpx2.Response(200, json=[])

    transport = httpx2.MockTransport(handler)
    _context._CLIENT = Client("http://test", transport=transport)
    opengrade.set_project("shared")
    client = opengrade.get_client()
    assert client is _context._CLIENT
    assert client._project_id == "p-shared"
    client.datasets.list()
    assert seen[-1] == "/api/v1/projects/p-shared/datasets"
    _context._reset_for_tests()


def test_client_without_project_id_raises() -> None:
    from opengrade import _context

    _context._reset_for_tests()

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=[])

    client = Client("http://test", transport=httpx2.MockTransport(handler))
    with pytest.raises(ValueError, match="project_id is required"):
        client.experiments.list()
    _context._reset_for_tests()

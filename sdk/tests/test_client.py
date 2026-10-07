from __future__ import annotations

import json
from typing import Any

import httpx2
import pytest

import aiobs
from aiobs import AiobsAPIError, Client
from aiobs.client import Client as ClientDirect


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
                    "task_type": "rag_qa",
                },
            )
        if method == "POST" and url.endswith("/items"):
            body = json.loads(request.content.decode()) if request.content else {}
            return httpx2.Response(201, json={"id": "item-1", "input": body.get("input")})
        if method == "GET" and "/datasets/ds-1" in url and "/items" not in url:
            return httpx2.Response(
                200,
                json={
                    "id": "ds-1",
                    "project_id": "proj-1",
                    "items": [{"id": "item-1", "input": "Q?"}],
                },
            )
        if method == "POST" and "/items/import" in url:
            return httpx2.Response(200, json={"created": 1, "errors": []})
        if method == "POST" and url.endswith("/experiments"):
            return httpx2.Response(201, json={"id": "exp-1", "name": "run", "dataset_id": "ds-1"})
        if method == "GET" and url.endswith("/outputs"):
            return httpx2.Response(200, json=[])
        if method == "POST" and url.endswith("/evaluate-pack"):
            return httpx2.Response(
                200,
                json={
                    "experiment": {"id": "exp-1", "status": "evaluated"},
                    "runs": [{"id": "run-1", "status": "completed", "results": []}],
                },
            )
        if method == "GET" and url.endswith("/summary"):
            return httpx2.Response(200, json={"experiment_id": "exp-1", "evaluators": []})
        if method == "GET" and "/compare/" in url:
            return httpx2.Response(200, json={"deltas": []})
        if method == "POST" and url.endswith("/metrics-pack/ensure"):
            return httpx2.Response(200, json={"entries": [{"kind": "hit_at_k"}]})
        if method == "POST" and "/live-interactions" in url:
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
        raise AssertionError(f"unexpected request: {method} {url}")

    return httpx2.MockTransport(handler)


def test_public_exports() -> None:
    assert "Client" in aiobs.__all__
    assert "AiobsAPIError" in aiobs.__all__
    assert Client is ClientDirect
    assert issubclass(AiobsAPIError, RuntimeError)


def test_health_and_projects(
    mock_transport: httpx2.MockTransport,
    captured_requests: list[httpx2.Request],
) -> None:
    client = Client("http://localhost:8000/", transport=mock_transport)
    assert client.health() == {"status": "ok"}
    project = client.projects.create(name="Demo", slug="demo")
    assert project["id"] == "proj-1"
    assert captured_requests[1].method == "POST"
    body: dict[str, Any] = json.loads(captured_requests[1].content.decode())
    assert body == {"name": "Demo", "slug": "demo"}
    assert client.projects.list() == []


def test_create_with_items_and_import(
    mock_transport: httpx2.MockTransport,
    captured_requests: list[httpx2.Request],
) -> None:
    client = Client("http://localhost:8000", transport=mock_transport)
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
    assert ds["id"] == "ds-1"
    methods = [r.method for r in captured_requests]
    assert methods == ["POST", "POST"]
    assert str(captured_requests[0].url).endswith("/projects/proj-1/datasets")
    assert str(captured_requests[1].url).endswith("/datasets/ds-1/items")
    item_body = json.loads(captured_requests[1].content.decode())
    assert item_body["input"] == "Q?"
    assert item_body["metadata"]["expected_doc_ids"] == ["d1"]

    detail = client.datasets.get("ds-1")
    assert len(detail["items"]) == 1

    imported = client.datasets.import_items(
        "ds-1",
        file=("gold.csv", b"question,expected_answer\nQ?,A\n"),
        format="csv",
    )
    assert imported["created"] == 1
    last = captured_requests[-1]
    assert "format=csv" in str(last.url)
    assert "/items/import" in str(last.url)
    assert b"gold.csv" in last.content


def test_experiments_and_metrics_pack(
    mock_transport: httpx2.MockTransport,
    captured_requests: list[httpx2.Request],
) -> None:
    client = Client(timeout=120.0, transport=mock_transport)
    pack = client.metrics_packs.ensure("proj-1")
    assert pack["entries"][0]["kind"] == "hit_at_k"

    exp = client.experiments.create(
        "proj-1",
        name="baseline",
        dataset_id="ds-1",
        model_config={"model": "m"},
        version="v1",
        baseline_experiment_id="exp-0",
    )
    assert exp["id"] == "exp-1"
    body = json.loads(captured_requests[-1].content.decode())
    assert body["baseline_experiment_id"] == "exp-0"
    assert body["model_config"] == {"model": "m"}

    assert client.experiments.list_outputs("exp-1") == []
    evaluated = client.experiments.evaluate_pack("exp-1")
    assert evaluated["experiment"]["status"] == "evaluated"
    assert client.experiments.summary("exp-1")["experiment_id"] == "exp-1"
    assert client.experiments.compare("exp-1", "exp-0") == {"deltas": []}


def test_live_runs_submit(
    mock_transport: httpx2.MockTransport,
    captured_requests: list[httpx2.Request],
) -> None:
    client = Client("http://localhost:8000", transport=mock_transport)
    result = client.live_runs.submit(
        "proj-1",
        question="What is PTO?",
        answer="Paid time off",
        documents=[{"id": "d1", "text": "PTO means paid time off"}],
        external_id="turn-1",
        metadata={"app": "hr"},
    )
    assert result["id"] == "live-1"
    assert result["judge_status"] == "pending"
    last = captured_requests[-1]
    assert last.method == "POST"
    assert str(last.url).endswith("/projects/proj-1/live-interactions")
    body = json.loads(last.content.decode())
    assert body["question"] == "What is PTO?"
    assert body["documents"][0]["id"] == "d1"
    assert body["external_id"] == "turn-1"

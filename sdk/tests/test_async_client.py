from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx2
import pytest

import opengrade
from opengrade import OpengradeAPIError, AsyncClient
from opengrade._http import _AsyncHttpTransport


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
        if method == "GET" and "/api/v1/projects/proj-1" in url and "live" not in url:
            return httpx2.Response(
                200,
                json={
                    "id": "proj-1",
                    "name": "Demo",
                    "slug": "demo",
                    "created_at": "2026-01-01T00:00:00+00:00",
                },
            )
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
        if method == "POST" and url.endswith("/projects/proj-1/trace-scores"):
            body = json.loads(request.content.decode()) if request.content else {}
            return httpx2.Response(202, json={"accepted": len(body.get("scores") or [])})
        if method == "GET" and url.endswith("/api/v1/projects/missing"):
            return httpx2.Response(404, text='{"detail":"missing"}')
        raise AssertionError(f"unexpected request: {method} {url}")

    return httpx2.MockTransport(handler)


def test_public_exports() -> None:
    assert "AsyncClient" in opengrade.__all__
    assert "get_async_client" in opengrade.__all__
    assert "aset_project" in opengrade.__all__


def test_async_transport_request_and_error() -> None:
    async def main() -> None:
        def ok_handler(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(200, json={"ok": True})

        transport = _AsyncHttpTransport(
            "http://localhost:8000/",
            transport=httpx2.MockTransport(ok_handler),
        )
        assert await transport.request("POST", "/api/v1/projects", body={"name": "Demo"}) == {
            "ok": True
        }
        await transport.aclose()

        def err_handler(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(404, text='{"detail":"missing"}')

        transport = _AsyncHttpTransport(
            "http://localhost:8000",
            transport=httpx2.MockTransport(err_handler),
        )
        with pytest.raises(OpengradeAPIError) as exc_info:
            await transport.request("GET", "/api/v1/projects/missing")
        assert exc_info.value.status == 404
        assert exc_info.value.detail == "missing"
        await transport.aclose()

    asyncio.run(main())


def test_health_and_projects(
    mock_transport: httpx2.MockTransport,
    captured_requests: list[httpx2.Request],
) -> None:
    async def main() -> None:
        async with AsyncClient("http://localhost:8000/", transport=mock_transport) as client:
            assert (await client.health()).status == "ok"
            project = await client.projects.create(name="Demo", slug="demo")
            assert project.id == "proj-1"
            body: dict[str, Any] = json.loads(captured_requests[1].content.decode())
            assert body == {"name": "Demo", "slug": "demo"}
            assert await client.projects.list() == []
            got = await client.projects.get("proj-1")
            assert got.slug == "demo"

    asyncio.run(main())


def test_live_runs_submit(
    mock_transport: httpx2.MockTransport,
    captured_requests: list[httpx2.Request],
) -> None:
    async def main() -> None:
        async with AsyncClient("http://localhost:8000", transport=mock_transport) as client:
            result = await client.live_runs.submit(
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

    asyncio.run(main())


def test_live_runs_list_get_promote_rescore(
    mock_transport: httpx2.MockTransport,
    captured_requests: list[httpx2.Request],
) -> None:
    async def main() -> None:
        async with AsyncClient("http://localhost:8000", transport=mock_transport) as client:
            listed = await client.live_runs.list("proj-1", failed_only=True, search="PTO", limit=10)
            assert len(listed.items) == 1
            assert listed.items[0].id == "live-1"
            list_req = captured_requests[-1]
            assert list_req.method == "GET"
            assert "failed_only=true" in str(list_req.url)
            assert "search=PTO" in str(list_req.url)

            detail = await client.live_runs.get("live-1")
            assert detail.judge_status == "scored"
            assert detail.scores[0].kind == "groundedness"

            promoted = await client.live_runs.promote(
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

            rescored = await client.live_runs.rescore("live-1")
            assert rescored.scores[0].score == 0.9
            assert captured_requests[-1].method == "POST"
            assert str(captured_requests[-1].url).endswith("/live-interactions/live-1/rescore")

    asyncio.run(main())


def test_trace_scores_log(
    mock_transport: httpx2.MockTransport,
    captured_requests: list[httpx2.Request],
) -> None:
    async def main() -> None:
        async with AsyncClient("http://localhost:8000", transport=mock_transport) as client:
            result = await client.trace_scores.log(
                "proj-1",
                [{"trace_id": "a" * 32, "name": "q", "value": 1.0}],
            )
            assert result.accepted == 1
            assert str(captured_requests[-1].url).endswith("/projects/proj-1/trace-scores")

    asyncio.run(main())


def test_api_error_from_async_client(mock_transport: httpx2.MockTransport) -> None:
    async def main() -> None:
        async with AsyncClient("http://localhost:8000", transport=mock_transport) as client:
            with pytest.raises(OpengradeAPIError) as exc_info:
                await client.projects.get("missing")
            assert exc_info.value.status == 404

    asyncio.run(main())

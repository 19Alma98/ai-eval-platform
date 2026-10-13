from __future__ import annotations

import json
from typing import Any

import httpx2

from aiobs import Client

TID = "ab" * 16


def test_client_logs_trace_scores() -> None:
    calls: list[tuple[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append((request.url.path, json.loads(request.content)))
        return httpx2.Response(202, json={"accepted": 1})

    client = Client("http://test", transport=httpx2.MockTransport(handler))
    result = client.trace_scores.log("p1", [{"trace_id": TID, "name": "q", "value": 1.0}])

    assert result.accepted == 1
    assert calls == [
        (
            "/api/v1/projects/p1/trace-scores",
            {"scores": [{"trace_id": TID, "name": "q", "value": 1.0}]},
        )
    ]

from __future__ import annotations

import json
import logging
import threading
from typing import Any

import httpx2
import pytest

from aiobs import Client
from aiobs._http import AiobsAPIError
from aiobs._scores import ScoreSender

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


class Recorder:
    def __init__(self, fail_times: int = 0, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, list[dict[str, Any]]]] = []
        self.fail_times = fail_times
        self.error = error or RuntimeError("server down")
        self.lock = threading.Lock()

    def __call__(self, project_id: str, scores: list[dict[str, Any]]) -> None:
        with self.lock:
            self.calls.append((project_id, list(scores)))
            if self.fail_times > 0:
                self.fail_times -= 1
                raise self.error


def _score(i: int) -> dict[str, Any]:
    return {"trace_id": TID, "name": f"m{i}", "value": 1.0}


def test_sender_batches_by_size_and_groups_projects() -> None:
    post = Recorder()
    sender = ScoreSender(post, batch_size=3, interval=60.0)
    for i in range(3):
        assert sender.enqueue("p1", _score(i))
    assert sender.enqueue("p2", _score(9))
    assert sender.flush(5.0)
    sent = {(project, tuple(s["name"] for s in scores)) for project, scores in post.calls}
    assert sent == {("p1", ("m0", "m1", "m2")), ("p2", ("m9",))}


def test_flush_with_nothing_queued_returns_immediately() -> None:
    assert ScoreSender(Recorder()).flush(0.1)


def test_full_queue_drops_with_one_warning(caplog: pytest.LogCaptureFixture) -> None:
    post = Recorder()
    sender = ScoreSender(post, max_queue=2, batch_size=100, interval=60.0)
    with caplog.at_level(logging.WARNING, logger="aiobs"):
        results = [sender.enqueue("p1", _score(i)) for i in range(5)]
    assert results == [True, True, False, False, False]
    assert sender.dropped == 3
    assert sum("queue full" in r.message for r in caplog.records) == 1
    assert sender.flush(5.0)
    assert [len(scores) for _, scores in post.calls] == [2]


def test_retries_once_then_succeeds() -> None:
    post = Recorder(fail_times=1)
    sender = ScoreSender(post, interval=60.0)
    sender.enqueue("p1", _score(0))
    assert sender.flush(5.0)
    assert len(post.calls) == 2


def test_drops_after_second_failure(caplog: pytest.LogCaptureFixture) -> None:
    post = Recorder(fail_times=5)
    sender = ScoreSender(post, interval=60.0)
    sender.enqueue("p1", _score(0))
    with caplog.at_level(logging.WARNING, logger="aiobs"):
        assert sender.flush(5.0)
    assert len(post.calls) == 2
    assert any("dropped 1 trace scores" in r.message for r in caplog.records)


def test_client_error_is_sent_once_and_dropped(caplog: pytest.LogCaptureFixture) -> None:
    post = Recorder(fail_times=5, error=AiobsAPIError(422, "invalid score"))
    sender = ScoreSender(post, interval=60.0)
    sender.enqueue("p1", _score(0))
    with caplog.at_level(logging.WARNING, logger="aiobs"):
        assert sender.flush(5.0)
    assert len(post.calls) == 1
    assert any("dropped 1 trace scores" in r.message for r in caplog.records)


def test_server_error_is_retried() -> None:
    post = Recorder(fail_times=1, error=AiobsAPIError(503, "unavailable"))
    sender = ScoreSender(post, interval=60.0)
    sender.enqueue("p1", _score(0))
    assert sender.flush(5.0)
    assert len(post.calls) == 2

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from aiobs.api.deps import (
    get_bind_otlp_traces,
    get_dataset_repository,
    get_experiment_item_output_repository,
    get_experiment_repository,
    get_project_repository,
    get_trace_repository,
)
from aiobs.domain.trace import Trace
from aiobs.main import create_app
from tests.test_api_experiment_outputs import (
    InMemoryDatasetRepository,
    InMemoryExperimentItemOutputRepository,
    InMemoryExperimentRepository,
    InMemoryProjectRepository,
    InMemoryTraceRepository,
)


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    import os

    from aiobs.config import get_settings

    os.environ["CONTENT_CAPTURE_ENABLED"] = "true"
    get_settings.cache_clear()

    projects = InMemoryProjectRepository()
    traces = InMemoryTraceRepository()
    datasets = InMemoryDatasetRepository()
    experiments = InMemoryExperimentRepository()
    outputs = InMemoryExperimentItemOutputRepository()

    app = create_app()
    app.dependency_overrides[get_project_repository] = lambda: projects
    app.dependency_overrides[get_trace_repository] = lambda: traces
    app.dependency_overrides[get_dataset_repository] = lambda: datasets
    app.dependency_overrides[get_experiment_repository] = lambda: experiments
    app.dependency_overrides[get_experiment_item_output_repository] = lambda: outputs

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    os.environ.pop("CONTENT_CAPTURE_ENABLED", None)
    get_settings.cache_clear()


async def _seed_rag_experiment(client: AsyncClient) -> tuple[str, str, str]:
    project = await client.post("/api/v1/projects", json={"name": "OTLP Bind"})
    assert project.status_code == 201
    project_id = project.json()["id"]

    dataset = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "rag-ds"},
    )
    assert dataset.status_code == 201
    dataset_id = dataset.json()["id"]

    item = await client.post(
        f"/api/v1/datasets/{dataset_id}/items",
        json={"input": "question", "expected_output": "answer"},
    )
    assert item.status_code == 201
    item_id = item.json()["id"]

    experiment = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "exp-bind", "dataset_id": dataset_id},
    )
    assert experiment.status_code == 201
    return project_id, experiment.json()["id"], item_id


def _otlp_payload(
    *,
    experiment_id: str,
    dataset_item_id: str,
    trace_id: str = "aa" * 16,
) -> dict[str, Any]:
    docs_json = json.dumps([{"id": "doc-1", "title": "Policy", "text": "Remote OK."}])
    return {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": "bb" * 8,
                                "name": "chain",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000001000000000",
                                "status": {"code": "STATUS_CODE_OK"},
                                "attributes": [
                                    {
                                        "key": "openinference.span.kind",
                                        "value": {"stringValue": "CHAIN"},
                                    },
                                    {
                                        "key": "aiobs.experiment_id",
                                        "value": {"stringValue": experiment_id},
                                    },
                                    {
                                        "key": "aiobs.dataset_item_id",
                                        "value": {"stringValue": dataset_item_id},
                                    },
                                    {
                                        "key": "output.value",
                                        "value": {"stringValue": "model answer from trace"},
                                    },
                                ],
                            },
                            {
                                "traceId": trace_id,
                                "spanId": "cc" * 8,
                                "parentSpanId": "bb" * 8,
                                "name": "retrieve",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000000500000000",
                                "status": {"code": "STATUS_CODE_OK"},
                                "attributes": [
                                    {
                                        "key": "openinference.span.kind",
                                        "value": {"stringValue": "RETRIEVER"},
                                    },
                                    {
                                        "key": "retrieval.documents",
                                        "value": {"stringValue": docs_json},
                                    },
                                ],
                            },
                        ]
                    }
                ]
            }
        ]
    }


@pytest.mark.asyncio
async def test_otlp_bind_attrs_upsert_experiment_outputs(client: AsyncClient) -> None:
    project_id, experiment_id, item_id = await _seed_rag_experiment(client)
    payload = _otlp_payload(experiment_id=experiment_id, dataset_item_id=item_id)

    otlp = await client.post(
        "/v1/traces",
        content=json.dumps(payload),
        headers={
            "content-type": "application/json",
            "X-Project-Id": project_id,
        },
    )
    assert otlp.status_code == 200

    listed = await client.get(f"/api/v1/experiments/{experiment_id}/outputs")
    assert listed.status_code == 200, listed.text
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["dataset_item_id"] == item_id
    assert rows[0]["actual_output"] == "model answer from trace"
    assert rows[0]["metadata"]["source_trace_id"] == "aa" * 16
    docs = rows[0]["context"]["documents"]
    assert len(docs) == 1
    assert docs[0]["id"] == "doc-1"
    assert docs[0]["text"] == "Remote OK."
    assert "latency_ms" in rows[0]["context"]

    traces = await client.get(f"/api/v1/projects/{project_id}/traces")
    assert traces.status_code == 200
    assert len(traces.json()["items"]) == 1


@pytest.mark.asyncio
async def test_otlp_unknown_experiment_still_stores_trace(client: AsyncClient) -> None:
    project_id, _experiment_id, item_id = await _seed_rag_experiment(client)
    missing_exp = str(uuid.uuid4())
    payload = _otlp_payload(experiment_id=missing_exp, dataset_item_id=item_id)

    otlp = await client.post(
        "/v1/traces",
        content=json.dumps(payload),
        headers={
            "content-type": "application/json",
            "X-Project-Id": project_id,
        },
    )
    assert otlp.status_code == 200

    traces = await client.get(f"/api/v1/projects/{project_id}/traces")
    assert len(traces.json()["items"]) == 1


class _FailingBindOtlpTraces:
    async def execute(self, traces: list[Trace]) -> None:
        raise RuntimeError("bind failed")


@pytest.mark.asyncio
async def test_otlp_bind_failure_still_stores_trace(client: AsyncClient) -> None:
    project_id, experiment_id, item_id = await _seed_rag_experiment(client)
    payload = _otlp_payload(experiment_id=experiment_id, dataset_item_id=item_id)

    app = client._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_bind_otlp_traces] = lambda: _FailingBindOtlpTraces()

    otlp = await client.post(
        "/v1/traces",
        content=json.dumps(payload),
        headers={
            "content-type": "application/json",
            "X-Project-Id": project_id,
        },
    )
    assert otlp.status_code == 200

    traces = await client.get(f"/api/v1/projects/{project_id}/traces")
    assert traces.status_code == 200
    assert len(traces.json()["items"]) == 1


@pytest.mark.asyncio
async def test_otlp_bind_preserves_existing_output_metadata(client: AsyncClient) -> None:
    project_id, experiment_id, item_id = await _seed_rag_experiment(client)
    seed = await client.put(
        f"/api/v1/experiments/{experiment_id}/outputs",
        json={
            "items": [
                {
                    "dataset_item_id": item_id,
                    "actual_output": "seed answer",
                    "metadata": {"model": "gpt-test", "prompt_rev": "3"},
                }
            ]
        },
    )
    assert seed.status_code == 200, seed.text

    payload = _otlp_payload(experiment_id=experiment_id, dataset_item_id=item_id)
    otlp = await client.post(
        "/v1/traces",
        content=json.dumps(payload),
        headers={
            "content-type": "application/json",
            "X-Project-Id": project_id,
        },
    )
    assert otlp.status_code == 200

    listed = await client.get(f"/api/v1/experiments/{experiment_id}/outputs")
    assert listed.status_code == 200
    row = listed.json()[0]
    assert row["metadata"]["model"] == "gpt-test"
    assert row["metadata"]["prompt_rev"] == "3"
    assert row["metadata"]["source_trace_id"] == "aa" * 16


@pytest.mark.asyncio
async def test_otlp_foreign_dataset_item_still_stores_trace(client: AsyncClient) -> None:
    project_id, experiment_id, _item_id = await _seed_rag_experiment(client)
    foreign_item = str(uuid.uuid4())
    payload = _otlp_payload(experiment_id=experiment_id, dataset_item_id=foreign_item)

    otlp = await client.post(
        "/v1/traces",
        content=json.dumps(payload),
        headers={
            "content-type": "application/json",
            "X-Project-Id": project_id,
        },
    )
    assert otlp.status_code == 200

    listed = await client.get(f"/api/v1/experiments/{experiment_id}/outputs")
    assert listed.status_code == 200
    assert listed.json() == []

    traces = await client.get(f"/api/v1/projects/{project_id}/traces")
    assert len(traces.json()["items"]) == 1

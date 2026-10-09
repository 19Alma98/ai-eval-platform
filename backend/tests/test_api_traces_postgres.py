from __future__ import annotations

import pytest
from httpx2 import AsyncClient

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_otlp_persist_and_get(client: AsyncClient) -> None:
    create_project = await client.post("/api/v1/projects", json={"name": "Trace Demo"})
    assert create_project.status_code == 201
    project_id = create_project.json()["id"]

    payload = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "11" * 16,
                                "spanId": "22" * 8,
                                "name": "root",
                                "startTimeUnixNano": "1700000000000000000",
                                "endTimeUnixNano": "1700000001000000000",
                                "status": {"code": "STATUS_CODE_OK"},
                                "attributes": [
                                    {
                                        "key": "openinference.span.kind",
                                        "value": {"stringValue": "CHAIN"},
                                    }
                                ],
                            },
                            {
                                "traceId": "11" * 16,
                                "spanId": "33" * 8,
                                "parentSpanId": "22" * 8,
                                "name": "llm",
                                "startTimeUnixNano": "1700000000500000000",
                                "endTimeUnixNano": "1700000000900000000",
                                "status": {"code": "STATUS_CODE_OK"},
                                "attributes": [
                                    {
                                        "key": "openinference.span.kind",
                                        "value": {"stringValue": "LLM"},
                                    },
                                    {
                                        "key": "gen_ai.request.model",
                                        "value": {"stringValue": "gpt-4o-mini"},
                                    },
                                ],
                            },
                        ]
                    }
                ]
            }
        ]
    }

    otlp = await client.post(
        "/v1/traces",
        json=payload,
        headers={"X-Project-Slug": create_project.json()["slug"]},
    )
    assert otlp.status_code == 200

    listed = await client.get(f"/api/v1/projects/{project_id}/traces")
    assert listed.status_code == 404

    created = await client.post(
        f"/api/v1/projects/{project_id}/traces",
        json={
            "trace_id": "ab" * 16,
            "name": "manual",
            "status": "ok",
            "start_time": "2024-01-01T00:00:00Z",
            "spans": [],
        },
    )
    assert created.status_code == 404

    detail = await client.get(f"/api/v1/projects/{project_id}/traces/{'11' * 16}")
    assert detail.status_code == 200
    spans = detail.json()["spans"]
    kinds = {s["kind"] for s in spans}
    assert kinds == {"CHAIN", "LLM"}

    # upsert same trace_id merges additional spans (OTLP clients often export per-span)
    payload2 = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "11" * 16,
                                "spanId": "44" * 8,
                                "name": "only",
                                "startTimeUnixNano": "1700000002000000000",
                                "endTimeUnixNano": "1700000003000000000",
                                "status": {"code": "STATUS_CODE_ERROR"},
                                "attributes": [
                                    {
                                        "key": "openinference.span.kind",
                                        "value": {"stringValue": "TOOL"},
                                    }
                                ],
                            }
                        ]
                    }
                ]
            }
        ]
    }
    again = await client.post(
        "/v1/traces",
        json=payload2,
        headers={"X-Project-Id": project_id},
    )
    assert again.status_code == 200
    detail2 = await client.get(f"/api/v1/projects/{project_id}/traces/{'11' * 16}")
    spans2 = detail2.json()["spans"]
    assert len(spans2) == 3
    kinds2 = {s["kind"] for s in spans2}
    assert kinds2 == {"CHAIN", "LLM", "TOOL"}
    assert detail2.json()["status"] == "error"


@pytest.mark.asyncio
async def test_rest_create_rejected(client: AsyncClient) -> None:
    create_project = await client.post("/api/v1/projects", json={"name": "REST Trace"})
    project_id = create_project.json()["id"]
    create = await client.post(
        f"/api/v1/projects/{project_id}/traces",
        json={
            "trace_id": "ab" * 16,
            "name": "manual",
            "status": "ok",
            "start_time": "2024-01-01T00:00:00Z",
            "spans": [],
        },
    )
    assert create.status_code == 404


@pytest.mark.asyncio
async def test_otlp_first_insert_binds_outputs_for_each_trace(client: AsyncClient) -> None:
    project = await client.post("/api/v1/projects", json={"name": "Bind Many"})
    assert project.status_code == 201
    project_id = project.json()["id"]

    dataset = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "ds", "task_type": "classification"},
    )
    dataset_id = dataset.json()["id"]
    item_ids: list[str] = []
    for i in range(2):
        item = await client.post(
            f"/api/v1/datasets/{dataset_id}/items",
            json={"input": f"q{i}", "expected_output": f"a{i}"},
        )
        assert item.status_code == 201
        item_ids.append(item.json()["id"])

    experiment = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "exp", "dataset_id": dataset_id},
    )
    experiment_id = experiment.json()["id"]

    for i, item_id in enumerate(item_ids):
        payload = {
            "resourceSpans": [
                {
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "traceId": f"{i + 1:02x}" * 16,
                                    "spanId": f"{i + 1:02x}" * 8,
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
                                            "value": {"stringValue": item_id},
                                        },
                                        {
                                            "key": "output.value",
                                            "value": {"stringValue": f"answer-{i}"},
                                        },
                                    ],
                                }
                            ]
                        }
                    ]
                }
            ]
        }
        otlp = await client.post(
            "/v1/traces",
            json=payload,
            headers={"X-Project-Id": project_id, "content-type": "application/json"},
        )
        assert otlp.status_code == 200, otlp.text

    listed = await client.get(f"/api/v1/experiments/{experiment_id}/outputs")
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 2
    by_item = {row["dataset_item_id"]: row["actual_output"] for row in rows}
    assert by_item[item_ids[0]] == "answer-0"
    assert by_item[item_ids[1]] == "answer-1"

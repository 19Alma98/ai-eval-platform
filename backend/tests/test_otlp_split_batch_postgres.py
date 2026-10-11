from __future__ import annotations

import json
from typing import Any

import pytest
from httpx2 import AsyncClient

pytestmark = pytest.mark.integration

TRACE_ID = "ab" * 16
ROOT_SPAN = "11" * 8
RETRIEVER_SPAN = "22" * 8


def _attrs(values: dict[str, str]) -> list[dict[str, Any]]:
    return [{"key": k, "value": {"stringValue": v}} for k, v in values.items()]


def _payload(*spans: dict[str, Any]) -> dict[str, Any]:
    return {"resourceSpans": [{"scopeSpans": [{"spans": list(spans)}]}]}


def _retriever_span() -> dict[str, Any]:
    return {
        "traceId": TRACE_ID,
        "spanId": RETRIEVER_SPAN,
        "parentSpanId": ROOT_SPAN,
        "name": "retrieve",
        "startTimeUnixNano": "1700000000000000000",
        "endTimeUnixNano": "1700000000100000000",
        "attributes": _attrs(
            {
                "openinference.span.kind": "RETRIEVER",
                "retrieval.documents": json.dumps([{"id": "pto", "text": "20 days"}]),
            }
        ),
    }


def _root_span(experiment_id: str, item_id: str) -> dict[str, Any]:
    return {
        "traceId": TRACE_ID,
        "spanId": ROOT_SPAN,
        "name": "rag",
        "startTimeUnixNano": "1700000000000000000",
        "endTimeUnixNano": "1700000001000000000",
        "attributes": _attrs(
            {
                "openinference.span.kind": "CHAIN",
                "output.value": "20 days",
                "aiobs.experiment_id": experiment_id,
                "aiobs.dataset_item_id": item_id,
            }
        ),
    }


async def _seed(client: AsyncClient) -> tuple[str, str, str]:
    project = (await client.post("/api/v1/projects", json={"name": "Split"})).json()
    dataset = (
        await client.post(
            f"/api/v1/projects/{project['id']}/datasets",
            json={"name": "gold", "task_type": "rag_qa"},
        )
    ).json()
    item = (
        await client.post(
            f"/api/v1/datasets/{dataset['id']}/items",
            json={
                "input": "How many PTO days?",
                "expected_output": "20 days",
                "metadata": {"expected_doc_ids": ["pto"]},
            },
        )
    ).json()
    experiment = (
        await client.post(
            f"/api/v1/projects/{project['id']}/experiments",
            json={"name": "run", "dataset_id": dataset["id"], "model_config": {}},
        )
    ).json()
    return project["slug"], experiment["id"], item["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("retriever_first", [True, False])
async def test_bound_output_keeps_documents_across_otlp_batches(
    client: AsyncClient, retriever_first: bool
) -> None:
    slug, experiment_id, item_id = await _seed(client)
    batches = [_payload(_retriever_span()), _payload(_root_span(experiment_id, item_id))]
    if not retriever_first:
        batches.reverse()
    for body in batches:
        resp = await client.post("/v1/traces", json=body, headers={"X-Project-Slug": slug})
        assert resp.status_code == 200

    outputs = (await client.get(f"/api/v1/experiments/{experiment_id}/outputs")).json()
    assert len(outputs) == 1
    assert outputs[0]["actual_output"] == "20 days"
    assert outputs[0]["context"]["documents"] == [{"id": "pto", "text": "20 days"}]

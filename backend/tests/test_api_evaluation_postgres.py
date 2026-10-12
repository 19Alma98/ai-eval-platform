from __future__ import annotations

import uuid

import pytest
from httpx2 import AsyncClient

pytestmark = pytest.mark.integration


async def _evaluate_outcome(client: AsyncClient, experiment_id: str) -> dict:
    """After a 202 evaluate, load terminal experiment + detailed runs."""
    exp = await client.get(f"/api/v1/experiments/{experiment_id}")
    assert exp.status_code == 200, exp.text
    assert exp.json()["status"] in {"completed", "failed"}, exp.json()
    runs = await client.get(f"/api/v1/experiments/{experiment_id}/runs")
    assert runs.status_code == 200, runs.text
    detailed = []
    for run in runs.json():
        detail = await client.get(f"/api/v1/evaluation-runs/{run['id']}")
        assert detail.status_code == 200, detail.text
        detailed.append(detail.json())
    return {"experiment": exp.json(), "runs": detailed}


@pytest.mark.asyncio
async def test_evaluate_persisted(client: AsyncClient) -> None:
    project = await client.post("/api/v1/projects", json={"name": "Eval PG"})
    assert project.status_code == 201
    project_id = project.json()["id"]

    dataset = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "ds1", "task_type": "classification"},
    )
    assert dataset.status_code == 201
    dataset_id = dataset.json()["id"]

    item = await client.post(
        f"/api/v1/datasets/{dataset_id}/items",
        json={"input": "q", "expected_output": "a", "actual_output": "a"},
    )
    assert item.status_code == 201

    evaluator = await client.post(
        f"/api/v1/projects/{project_id}/evaluators",
        json={
            "name": "exact",
            "type": "deterministic",
            "config": {"kind": "exact_match"},
        },
    )
    assert evaluator.status_code == 201
    evaluator_id = evaluator.json()["id"]

    experiment = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "exp1", "dataset_id": dataset_id},
    )
    assert experiment.status_code == 201
    experiment_id = experiment.json()["id"]

    evaluated = await client.post(
        f"/api/v1/experiments/{experiment_id}/evaluate",
        json={"evaluator_ids": [evaluator_id]},
    )
    assert evaluated.status_code == 202
    assert evaluated.json()["status"] == "running"
    body = await _evaluate_outcome(client, experiment_id)
    assert body["experiment"]["status"] == "completed"
    assert len(body["runs"]) == 1
    assert body["runs"][0]["results"][0]["score"] == 1.0
    assert uuid.UUID(body["runs"][0]["id"])

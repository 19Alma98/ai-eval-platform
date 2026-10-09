from __future__ import annotations

import pytest
from httpx2 import AsyncClient

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_compare_persisted(client: AsyncClient) -> None:
    project = await client.post("/api/v1/projects", json={"name": "Compare PG"})
    assert project.status_code == 201
    project_id = project.json()["id"]

    dataset = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "shared", "task_type": "classification"},
    )
    dataset_id = dataset.json()["id"]
    bad_item_id = None
    for idx in range(5):
        item = await client.post(
            f"/api/v1/datasets/{dataset_id}/items",
            json={
                "input": f"q{idx}",
                "expected_output": "a",
                "actual_output": "a",
            },
        )
        assert item.status_code == 201
        if idx == 1:
            bad_item_id = item.json()["id"]
    assert bad_item_id is not None

    evaluator = await client.post(
        f"/api/v1/projects/{project_id}/evaluators",
        json={
            "name": "exact",
            "type": "deterministic",
            "config": {"kind": "exact_match"},
        },
    )
    evaluator_id = evaluator.json()["id"]

    baseline = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "baseline", "dataset_id": dataset_id},
    )
    baseline_id = baseline.json()["id"]
    candidate = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "candidate", "dataset_id": dataset_id},
    )
    candidate_id = candidate.json()["id"]

    put = await client.put(
        f"/api/v1/experiments/{candidate_id}/outputs",
        json={"items": [{"dataset_item_id": bad_item_id, "actual_output": "b"}]},
    )
    assert put.status_code == 200

    for experiment_id in (baseline_id, candidate_id):
        evaluated = await client.post(
            f"/api/v1/experiments/{experiment_id}/evaluate",
            json={"evaluator_ids": [evaluator_id]},
        )
        assert evaluated.status_code == 200

    summary = await client.get(f"/api/v1/experiments/{baseline_id}/summary")
    assert summary.status_code == 200
    assert summary.json()["evaluators"][0]["mean_score"] == 1.0

    compare = await client.get(f"/api/v1/experiments/{candidate_id}/compare/{baseline_id}")
    assert compare.status_code == 200
    body = compare.json()
    assert len(body["candidate_runs"]) == 1
    assert len(body["baseline_runs"]) == 1
    assert all(m["status"] == "regression" for m in body["metrics"])

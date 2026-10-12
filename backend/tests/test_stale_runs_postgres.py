from __future__ import annotations

from typing import Any

import pytest
from httpx2 import AsyncClient

pytestmark = pytest.mark.integration


async def _project(client: AsyncClient) -> tuple[str, str]:
    project = (await client.post("/api/v1/projects", json={"name": "Stale"})).json()
    dataset = (
        await client.post(
            f"/api/v1/projects/{project['id']}/datasets",
            json={"name": "gold", "task_type": "rag_qa"},
        )
    ).json()
    return project["id"], dataset["id"]


async def _add_items(client: AsyncClient, dataset_id: str, start: int, n: int) -> list[dict]:
    items = []
    for i in range(start, start + n):
        resp = await client.post(
            f"/api/v1/datasets/{dataset_id}/items",
            json={
                "input": f"q{i}",
                "expected_output": "a",
                "metadata": {"expected_doc_ids": [f"d{i}"]},
            },
        )
        assert resp.status_code == 201
        items.append(resp.json())
    return items


async def _metrics_set(client: AsyncClient, project_id: str, name: str, kinds: list[str]) -> str:
    entries = [{"kind": k, "enabled": True, "threshold": 0.5, "config": {"k": 5}} for k in kinds]
    resp = await client.post(
        f"/api/v1/projects/{project_id}/metrics-sets", json={"name": name, "entries": entries}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _experiment(client: AsyncClient, project_id: str, dataset_id: str, name: str) -> str:
    resp = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": name, "dataset_id": dataset_id, "model_config": {}},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def _outputs(
    client: AsyncClient, experiment_id: str, items: list[dict], *, hit: bool
) -> None:
    body: dict[str, Any] = {
        "items": [
            {
                "dataset_item_id": it["id"],
                "actual_output": "a",
                "context": {
                    "documents": [{"id": it["metadata"]["expected_doc_ids"][0] if hit else "zz"}]
                },
            }
            for it in items
        ]
    }
    resp = await client.put(f"/api/v1/experiments/{experiment_id}/outputs", json=body)
    assert resp.status_code == 200, resp.text


async def _score(client: AsyncClient, experiment_id: str, metrics_set_id: str) -> None:
    resp = await client.post(
        f"/api/v1/experiments/{experiment_id}/evaluate-pack",
        json={"metrics_set_id": metrics_set_id},
    )
    assert resp.status_code == 202, resp.text


@pytest.mark.asyncio
async def test_release_check_ignores_runs_scored_on_old_outputs(client: AsyncClient) -> None:
    project_id, dataset_id = await _project(client)
    items = await _add_items(client, dataset_id, 0, 6)
    both = await _metrics_set(client, project_id, "both", ["hit_at_k", "mrr"])
    hit_only = await _metrics_set(client, project_id, "hit", ["hit_at_k"])
    experiment_id = await _experiment(client, project_id, dataset_id, "run")

    await _outputs(client, experiment_id, items, hit=True)
    await _score(client, experiment_id, both)
    # The app re-ran and now misses every document; only hit_at_k is re-scored.
    await _outputs(client, experiment_id, items, hit=False)
    await _score(client, experiment_id, hit_only)

    summary = (await client.get(f"/api/v1/experiments/{experiment_id}/summary")).json()
    assert [e["evaluator_name"] for e in summary["evaluators"]] == ["hit_at_k"]

    check = await client.post(
        f"/api/v1/projects/{project_id}/release-check",
        json={"experiment_id": experiment_id, "policy": {"mrr": {"min": 0.9}}},
    )
    assert check.status_code == 200
    body = check.json()
    assert body["status"] == "failed"
    assert body["checks"][0]["status"] == "unavailable"


@pytest.mark.asyncio
async def test_compare_rejects_baseline_scored_before_test_set_changed(
    client: AsyncClient,
) -> None:
    project_id, dataset_id = await _project(client)
    items = await _add_items(client, dataset_id, 0, 6)
    ms = await _metrics_set(client, project_id, "hit", ["hit_at_k"])
    baseline_id = await _experiment(client, project_id, dataset_id, "baseline")
    await _outputs(client, baseline_id, items, hit=True)
    await _score(client, baseline_id, ms)

    items += await _add_items(client, dataset_id, 6, 6)
    candidate_id = await _experiment(client, project_id, dataset_id, "candidate")
    await _outputs(client, candidate_id, items, hit=True)
    await _score(client, candidate_id, ms)

    resp = await client.get(f"/api/v1/experiments/{candidate_id}/compare/{baseline_id}")
    assert resp.status_code == 400, resp.text
    assert "re-score" in resp.text

    # Re-scoring the baseline on the current test set makes the pair comparable again.
    await _score(client, baseline_id, ms)
    resp = await client.get(f"/api/v1/experiments/{candidate_id}/compare/{baseline_id}")
    assert resp.status_code == 200, resp.text

from __future__ import annotations

from typing import Any

import pytest
from httpx2 import AsyncClient

import test_api_evaluation

client = test_api_evaluation.client  # shared in-memory app fixture

N_ITEMS = 6


async def _setup(client: AsyncClient) -> dict[str, Any]:
    project = await client.post("/api/v1/projects", json={"name": "Client Scores"})
    project_id = project.json()["id"]
    dataset = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "gold", "task_type": "classification"},
    )
    dataset_id = dataset.json()["id"]
    item_ids = []
    for i in range(N_ITEMS):
        item = await client.post(
            f"/api/v1/datasets/{dataset_id}/items",
            json={"input": f"q{i}", "expected_output": f"a{i}"},
        )
        assert item.status_code == 201, item.text
        item_ids.append(item.json()["id"])
    return {"project_id": project_id, "dataset_id": dataset_id, "item_ids": item_ids}


async def _experiment(client: AsyncClient, ctx: dict[str, Any], name: str) -> str:
    exp = await client.post(
        f"/api/v1/projects/{ctx['project_id']}/experiments",
        json={"name": name, "dataset_id": ctx["dataset_id"]},
    )
    assert exp.status_code == 201, exp.text
    exp_id = exp.json()["id"]
    put = await client.put(
        f"/api/v1/experiments/{exp_id}/outputs",
        json={"items": [{"dataset_item_id": i, "actual_output": "x"} for i in ctx["item_ids"]]},
    )
    assert put.status_code == 200, put.text
    return exp_id


def _metric(item_ids: list[str], scores: list[float | None], **extra: Any) -> dict[str, Any]:
    return {
        "name": extra.pop("name", "my_metric"),
        "results": [
            {"dataset_item_id": i, "score": s} for i, s in zip(item_ids, scores, strict=True)
        ],
        **extra,
    }


@pytest.mark.asyncio
async def test_submit_creates_run_visible_in_summary(client: AsyncClient) -> None:
    ctx = await _setup(client)
    exp_id = await _experiment(client, ctx, "cand")
    scores = [1.0, 0.5, 0.0, 1.0, None, 0.25]

    resp = await client.post(
        f"/api/v1/experiments/{exp_id}/client-results",
        json={"metrics": [_metric(ctx["item_ids"], scores, threshold=0.5)]},
    )
    assert resp.status_code == 201, resp.text
    (run,) = resp.json()
    assert run["status"] == "FAILED"
    assert run["metadata"]["evaluator_name"] == "my_metric"
    assert run["metadata"]["evaluator_kind"] == "client"
    assert run["metadata"]["source"] == "client"
    assert run["metadata"]["inputs_fingerprint"]
    labels = [r["label"] for r in run["results"]]
    assert labels == ["PASS", "PASS", "FAIL", "PASS", "SKIPPED", "FAIL"]

    summary = await client.get(f"/api/v1/experiments/{exp_id}/summary")
    (row,) = summary.json()["evaluators"]
    assert row["evaluator_name"] == "my_metric"
    assert row["n_skipped"] == 1
    assert row["mean_score"] == pytest.approx((1.0 + 0.5 + 0.0 + 1.0 + 0.25) / 5)
    assert row["pass_rate"] == pytest.approx(3 / 5)


@pytest.mark.asyncio
async def test_compare_against_baseline_uses_client_runs(client: AsyncClient) -> None:
    ctx = await _setup(client)
    base_id = await _experiment(client, ctx, "base")
    cand_id = await _experiment(client, ctx, "cand")
    for exp_id, score in ((base_id, 1.0), (cand_id, 0.0)):
        resp = await client.post(
            f"/api/v1/experiments/{exp_id}/client-results",
            json={"metrics": [_metric(ctx["item_ids"], [score] * N_ITEMS)]},
        )
        assert resp.status_code == 201, resp.text

    # Same evaluator reused across experiments, so compare pairs the runs.
    compare = await client.get(f"/api/v1/experiments/{cand_id}/compare/{base_id}")
    assert compare.status_code == 200, compare.text
    mean = next(m for m in compare.json()["metrics"] if m["metric"] == "mean_score")
    assert mean["evaluator_name"] == "my_metric"
    assert mean["delta"] == pytest.approx(-1.0)
    assert mean["status"] == "regression"


@pytest.mark.asyncio
async def test_config_change_flags_mismatch(client: AsyncClient) -> None:
    ctx = await _setup(client)
    base_id = await _experiment(client, ctx, "base")
    cand_id = await _experiment(client, ctx, "cand")
    for exp_id, version in ((base_id, 1), (cand_id, 2)):
        await client.post(
            f"/api/v1/experiments/{exp_id}/client-results",
            json={
                "metrics": [_metric(ctx["item_ids"], [1.0] * N_ITEMS, config={"version": version})]
            },
        )
    compare = await client.get(f"/api/v1/experiments/{cand_id}/compare/{base_id}")
    assert {m["status"] for m in compare.json()["metrics"]} == {"config_mismatch"}


@pytest.mark.asyncio
async def test_resubmit_latest_wins_and_outputs_change_makes_stale(
    client: AsyncClient,
) -> None:
    ctx = await _setup(client)
    exp_id = await _experiment(client, ctx, "cand")
    url = f"/api/v1/experiments/{exp_id}/client-results"
    await client.post(url, json={"metrics": [_metric(ctx["item_ids"], [0.0] * N_ITEMS)]})
    await client.post(url, json={"metrics": [_metric(ctx["item_ids"], [1.0] * N_ITEMS)]})

    summary = await client.get(f"/api/v1/experiments/{exp_id}/summary")
    (row,) = summary.json()["evaluators"]
    assert row["mean_score"] == pytest.approx(1.0)

    await client.put(
        f"/api/v1/experiments/{exp_id}/outputs",
        json={"items": [{"dataset_item_id": ctx["item_ids"][0], "actual_output": "changed"}]},
    )
    summary = await client.get(f"/api/v1/experiments/{exp_id}/summary")
    assert summary.json()["evaluators"] == []


@pytest.mark.asyncio
async def test_validation_errors(client: AsyncClient) -> None:
    ctx = await _setup(client)
    exp_id = await _experiment(client, ctx, "cand")
    url = f"/api/v1/experiments/{exp_id}/client-results"
    item = ctx["item_ids"][0]

    unknown_item = {"name": "m", "results": [{"dataset_item_id": ctx["project_id"], "score": 1}]}
    dup_item = {
        "name": "m",
        "results": [{"dataset_item_id": item, "score": 1}, {"dataset_item_id": item, "score": 0}],
    }
    bad_label = {"name": "m", "results": [{"dataset_item_id": item, "label": "MAYBE"}]}
    one = {"name": "m", "results": [{"dataset_item_id": item, "score": 1}]}

    assert (await client.post(url, json={"metrics": [unknown_item]})).status_code == 400
    assert (await client.post(url, json={"metrics": [dup_item]})).status_code == 400
    assert (await client.post(url, json={"metrics": [bad_label]})).status_code == 400
    assert (await client.post(url, json={"metrics": [one, one]})).status_code == 400
    assert (await client.post(url, json={"metrics": []})).status_code == 422
    nan = f'{{"metrics":[{{"name":"m","results":[{{"dataset_item_id":"{item}","score":NaN}}]}}]}}'
    resp = await client.post(url, content=nan, headers={"content-type": "application/json"})
    assert resp.status_code == 400
    missing = "/api/v1/experiments/00000000-0000-0000-0000-000000000000/client-results"
    assert (await client.post(missing, json={"metrics": [one]})).status_code == 404
    # Nothing was written by the rejected calls.
    runs = await client.get(f"/api/v1/experiments/{exp_id}/runs")
    assert runs.json() == []


@pytest.mark.asyncio
async def test_name_used_by_server_evaluator_conflicts(client: AsyncClient) -> None:
    ctx = await _setup(client)
    exp_id = await _experiment(client, ctx, "cand")
    created = await client.post(
        f"/api/v1/projects/{ctx['project_id']}/evaluators",
        json={"name": "exact", "type": "deterministic", "config": {"kind": "exact_match"}},
    )
    assert created.status_code == 201
    resp = await client.post(
        f"/api/v1/experiments/{exp_id}/client-results",
        json={"metrics": [_metric(ctx["item_ids"], [1.0] * N_ITEMS, name="exact")]},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_client_evaluator_cannot_be_run_by_server(client: AsyncClient) -> None:
    ctx = await _setup(client)
    exp_id = await _experiment(client, ctx, "cand")
    resp = await client.post(
        f"/api/v1/experiments/{exp_id}/client-results",
        json={"metrics": [_metric(ctx["item_ids"], [1.0] * N_ITEMS)]},
    )
    evaluator_id = resp.json()[0]["evaluator_id"]

    evaluate = await client.post(
        f"/api/v1/experiments/{exp_id}/evaluate", json={"evaluator_ids": [evaluator_id]}
    )
    assert evaluate.status_code == 400
    assert "client" in evaluate.json()["detail"]

    metrics_set = await client.post(
        f"/api/v1/projects/{ctx['project_id']}/metrics-sets",
        json={
            "name": "with-client",
            "entries": [{"kind": "my_metric", "enabled": True, "evaluator_id": evaluator_id}],
        },
    )
    assert metrics_set.status_code == 400

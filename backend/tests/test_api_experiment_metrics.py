from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx2 import AsyncClient

import test_api_evaluation

client = test_api_evaluation.client  # shared in-memory app fixture


async def _setup(client: AsyncClient) -> dict[str, Any]:
    project = await client.post("/api/v1/projects", json={"name": "Experiment Metrics"})
    project_id = project.json()["id"]
    dataset = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "gold", "task_type": "classification"},
    )
    dataset_id = dataset.json()["id"]
    item_ids = []
    for i in range(3):
        item = await client.post(
            f"/api/v1/datasets/{dataset_id}/items",
            json={"input": f"q{i}", "expected_output": f"a{i}"},
        )
        assert item.status_code == 201, item.text
        item_ids.append(item.json()["id"])
    return {"project_id": project_id, "dataset_id": dataset_id, "item_ids": item_ids}


async def _experiment(client: AsyncClient, ctx: dict[str, Any], name: str, **extra: Any) -> str:
    exp = await client.post(
        f"/api/v1/projects/{ctx['project_id']}/experiments",
        json={"name": name, "dataset_id": ctx["dataset_id"], **extra},
    )
    assert exp.status_code == 201, exp.text
    return str(exp.json()["id"])


async def _score(client: AsyncClient, ctx: dict[str, Any], exp_id: str, score: float) -> None:
    put = await client.put(
        f"/api/v1/experiments/{exp_id}/outputs",
        json={"items": [{"dataset_item_id": i, "actual_output": "x"} for i in ctx["item_ids"]]},
    )
    assert put.status_code == 200, put.text
    resp = await client.post(
        f"/api/v1/experiments/{exp_id}/client-results",
        json={
            "metrics": [
                {
                    "name": "quality",
                    "results": [{"dataset_item_id": i, "score": score} for i in ctx["item_ids"]],
                }
            ]
        },
    )
    assert resp.status_code == 201, resp.text


async def _put_metrics(client: AsyncClient, exp_id: str, metrics: dict[str, Any]) -> Any:
    return await client.put(f"/api/v1/experiments/{exp_id}/metrics", json={"metrics": metrics})


async def test_put_metrics_upserts_and_get_returns_all(client: AsyncClient) -> None:
    ctx = await _setup(client)
    exp_id = await _experiment(client, ctx, "cand")

    first = await _put_metrics(client, exp_id, {"cost_usd": 1.5, "aiobs.error_rate": 0})
    assert first.status_code == 200, first.text
    assert first.json() == {
        "experiment_id": exp_id,
        "metrics": {"aiobs.error_rate": 0.0, "cost_usd": 1.5},
    }

    second = await _put_metrics(client, exp_id, {"cost_usd": 2})
    assert second.json()["metrics"] == {"aiobs.error_rate": 0.0, "cost_usd": 2.0}

    got = await client.get(f"/api/v1/experiments/{exp_id}/metrics")
    assert got.status_code == 200, got.text
    assert got.json()["metrics"] == {"aiobs.error_rate": 0.0, "cost_usd": 2.0}


@pytest.mark.parametrize(
    "metrics",
    [{}, {"has space": 1.0}, {"x" * 201: 1.0}, {"ok": "1.0"}, {"ok": True}, {"ok": None}],
)
async def test_put_metrics_rejects_invalid(client: AsyncClient, metrics: dict[str, Any]) -> None:
    ctx = await _setup(client)
    exp_id = await _experiment(client, ctx, "cand")
    resp = await _put_metrics(client, exp_id, metrics)
    assert resp.status_code == 400, resp.text


async def test_put_metrics_non_finite_and_unknown_experiment(client: AsyncClient) -> None:
    ctx = await _setup(client)
    exp_id = await _experiment(client, ctx, "cand")
    nan = await client.put(
        f"/api/v1/experiments/{exp_id}/metrics",
        content=b'{"metrics": {"x": NaN}}',
        headers={"content-type": "application/json"},
    )
    assert nan.status_code == 422, nan.text

    unknown = uuid.uuid4()
    assert (await _put_metrics(client, str(unknown), {"x": 1.0})).status_code == 404
    assert (await client.get(f"/api/v1/experiments/{unknown}/metrics")).status_code == 404


async def test_patch_params_merges_until_scored(client: AsyncClient) -> None:
    ctx = await _setup(client)
    exp_id = await _experiment(client, ctx, "cand", model_config={"model": "a", "temperature": 0.1})

    resp = await client.patch(
        f"/api/v1/experiments/{exp_id}/params",
        json={"params": {"temperature": 0.2, "top_p": 0.9}},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["model_config"] == {"model": "a", "temperature": 0.2, "top_p": 0.9}

    empty = await client.patch(f"/api/v1/experiments/{exp_id}/params", json={"params": {}})
    assert empty.status_code == 400, empty.text

    await _score(client, ctx, exp_id, 1.0)
    locked = await client.patch(
        f"/api/v1/experiments/{exp_id}/params", json={"params": {"model": "b"}}
    )
    assert locked.status_code == 409, locked.text
    assert "locked" in locked.json()["detail"]

    unknown = await client.patch(
        f"/api/v1/experiments/{uuid.uuid4()}/params", json={"params": {"a": 1}}
    )
    assert unknown.status_code == 404


async def test_summary_includes_experiment_metrics(client: AsyncClient) -> None:
    ctx = await _setup(client)
    exp_id = await _experiment(client, ctx, "cand")

    empty = await client.get(f"/api/v1/experiments/{exp_id}/summary")
    assert empty.status_code == 200, empty.text
    assert empty.json()["evaluators"] == []
    assert empty.json()["experiment_metrics"] == {}

    await _put_metrics(client, exp_id, {"cost_usd": 1.5})
    summary = await client.get(f"/api/v1/experiments/{exp_id}/summary")
    assert summary.json()["experiment_metrics"] == {"cost_usd": 1.5}

    await _score(client, ctx, exp_id, 1.0)
    scored = await client.get(f"/api/v1/experiments/{exp_id}/summary")
    assert scored.status_code == 200, scored.text
    assert scored.json()["evaluators"] != []
    assert scored.json()["experiment_metrics"] == {"cost_usd": 1.5}


async def test_compare_reports_experiment_metric_deltas(client: AsyncClient) -> None:
    ctx = await _setup(client)
    base = await _experiment(client, ctx, "base")
    cand = await _experiment(client, ctx, "cand")
    for exp_id in (base, cand):
        await _score(client, ctx, exp_id, 1.0)
    await _put_metrics(client, base, {"cost_usd": 1.0, "only_base": 3.0})
    await _put_metrics(client, cand, {"cost_usd": 1.5, "only_cand": 1.0})

    resp = await client.get(f"/api/v1/experiments/{cand}/compare/{base}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["experiment_metrics"] == [
        {"key": "cost_usd", "candidate": 1.5, "baseline": 1.0, "delta": 0.5},
        {"key": "only_base", "candidate": None, "baseline": 3.0, "delta": None},
        {"key": "only_cand", "candidate": 1.0, "baseline": None, "delta": None},
    ]


async def test_release_check_experiment_metric_rules(client: AsyncClient) -> None:
    ctx = await _setup(client)
    exp_id = await _experiment(client, ctx, "cand")
    await _put_metrics(client, exp_id, {"cost_usd": 1.5, "accuracy": 0.7})

    resp = await client.post(
        f"/api/v1/projects/{ctx['project_id']}/release-check",
        json={
            "experiment_id": exp_id,
            "policy": {
                "experiment_metrics": {
                    "cost_usd": {"max": 2.0},
                    "accuracy": {"min": 0.8},
                    "missing": {"min": 0},
                }
            },
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "failed"
    assert [(c["metric"], c["actual"], c["threshold"], c["status"]) for c in body["checks"]] == [
        ("experiment_metrics.cost_usd.max", 1.5, 2.0, "passed"),
        ("experiment_metrics.accuracy.min", 0.7, 0.8, "failed"),
        ("experiment_metrics.missing.min", None, 0.0, "unavailable"),
    ]


@pytest.mark.parametrize("rule", [{}, {"avg": 1.0}])
async def test_release_check_rejects_bad_experiment_metric_rule(
    client: AsyncClient, rule: dict[str, Any]
) -> None:
    ctx = await _setup(client)
    exp_id = await _experiment(client, ctx, "cand")
    resp = await client.post(
        f"/api/v1/projects/{ctx['project_id']}/release-check",
        json={"experiment_id": exp_id, "policy": {"experiment_metrics": {"cost_usd": rule}}},
    )
    assert resp.status_code == 422, resp.text

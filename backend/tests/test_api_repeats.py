"""Repeated runs of one item (``repeat`` index) on a real SQLite schema."""

from __future__ import annotations

from typing import Any

import pytest
from httpx2 import AsyncClient

import test_sqlite_smoke
from opengrade_server.domain.evaluation import EvaluationResultRecord
from opengrade_server.regression.aggregate import (
    aggregate_results,
    collapse_repeats,
    paired_item_diffs,
)

sqlite_client = test_sqlite_smoke.sqlite_client

N_ITEMS = 6
N_REPEATS = 3


def _record(item: Any, repeat: int, score: float | None, label: str) -> EvaluationResultRecord:
    return EvaluationResultRecord.create(
        run_id=item, dataset_item_id=item, score=score, label=label, repeat=repeat
    )


def test_aggregate_weighs_each_item_once() -> None:
    import uuid

    a, b = uuid.uuid4(), uuid.uuid4()
    results = [
        _record(a, 0, 1.0, "PASS"),
        _record(a, 1, 0.0, "FAIL"),
        _record(a, 2, 1.0, "PASS"),
        _record(b, 0, 0.0, "FAIL"),
    ]
    agg = aggregate_results(results)
    assert agg.n_items == 2
    assert agg.n_repeats == 3
    assert agg.n_flaky == 1
    assert agg.mean_score == pytest.approx(((2 / 3) + 0.0) / 2)
    assert agg.pass_rate == pytest.approx(((2 / 3) + 0.0) / 2)

    collapsed = collapse_repeats(results[:3])
    assert collapsed.score == pytest.approx(2 / 3)
    assert collapsed.label == "PASS"
    assert collapsed.metadata["repeats"]["flaky"] is True
    assert collapsed.metadata["repeats"]["n"] == 3


def test_skipped_repeats_are_not_applicable() -> None:
    import uuid

    a = uuid.uuid4()
    results = [_record(a, 0, None, "SKIPPED"), _record(a, 1, 1.0, "PASS")]
    agg = aggregate_results(results)
    assert agg.n_applicable == 1
    assert agg.mean_score == pytest.approx(1.0)
    assert agg.n_flaky == 0


def test_paired_diffs_pair_item_means() -> None:
    import uuid

    a, b = uuid.uuid4(), uuid.uuid4()
    cand = [_record(a, 0, 1.0, "PASS"), _record(a, 1, 0.0, "FAIL"), _record(b, 0, 1.0, "PASS")]
    base = [_record(a, 0, 0.0, "FAIL"), _record(b, 0, 1.0, "PASS")]
    diffs = paired_item_diffs(cand, base, metric="mean_score")
    assert sorted(diffs) == pytest.approx([0.0, 0.5])


async def _setup(client: AsyncClient) -> dict[str, Any]:
    project = (await client.post("/api/v1/projects", json={"name": "Repeats"})).json()
    dataset = (
        await client.post(
            f"/api/v1/projects/{project['id']}/datasets",
            json={"name": "gold", "task_type": "classification"},
        )
    ).json()
    item_ids = []
    for i in range(N_ITEMS):
        item = await client.post(
            f"/api/v1/datasets/{dataset['id']}/items",
            json={"input": f"q{i}", "expected_output": "yes"},
        )
        assert item.status_code == 201, item.text
        item_ids.append(item.json()["id"])
    evaluator = await client.post(
        f"/api/v1/projects/{project['id']}/evaluators",
        json={"name": "exact", "type": "deterministic", "config": {"kind": "exact_match"}},
    )
    assert evaluator.status_code == 201, evaluator.text
    return {
        "project_id": project["id"],
        "dataset_id": dataset["id"],
        "item_ids": item_ids,
        "evaluator_id": evaluator.json()["id"],
    }


async def _experiment(
    client: AsyncClient, ctx: dict[str, Any], name: str, outputs: list[list[str]]
) -> str:
    exp = await client.post(
        f"/api/v1/projects/{ctx['project_id']}/experiments",
        json={"name": name, "dataset_id": ctx["dataset_id"]},
    )
    assert exp.status_code == 201, exp.text
    exp_id = exp.json()["id"]
    items = [
        {"dataset_item_id": item_id, "repeat": repeat, "actual_output": out}
        for item_id, per_repeat in zip(ctx["item_ids"], outputs, strict=True)
        for repeat, out in enumerate(per_repeat)
    ]
    put = await client.put(f"/api/v1/experiments/{exp_id}/outputs", json={"items": items})
    assert put.status_code == 200, put.text
    evaluated = await client.post(
        f"/api/v1/experiments/{exp_id}/evaluate",
        json={"evaluator_ids": [ctx["evaluator_id"]]},
    )
    assert evaluated.status_code == 202, evaluated.text
    return exp_id


@pytest.mark.asyncio
async def test_repeats_are_stored_scored_and_aggregated(sqlite_client: AsyncClient) -> None:
    ctx = await _setup(sqlite_client)
    # Item 0 is flaky (1 of 3 repeats wrong); the others always answer right.
    outputs = [["yes", "no", "yes"]] + [["yes"] * N_REPEATS for _ in range(N_ITEMS - 1)]
    exp_id = await _experiment(sqlite_client, ctx, "cand", outputs)

    stored = (await sqlite_client.get(f"/api/v1/experiments/{exp_id}/outputs")).json()
    assert len(stored) == N_ITEMS * N_REPEATS
    assert {o["repeat"] for o in stored} == {0, 1, 2}

    summary = (await sqlite_client.get(f"/api/v1/experiments/{exp_id}/summary")).json()
    (row,) = summary["evaluators"]
    assert row["n_items"] == N_ITEMS
    assert row["n_repeats"] == N_REPEATS
    assert row["n_flaky"] == 1
    assert row["mean_score"] == pytest.approx((2 / 3 + (N_ITEMS - 1)) / N_ITEMS)

    run = (await sqlite_client.get(f"/api/v1/evaluation-runs/{row['run_id']}")).json()
    assert len(run["results"]) == N_ITEMS * N_REPEATS
    assert {r["repeat"] for r in run["results"]} == {0, 1, 2}


@pytest.mark.asyncio
async def test_compare_items_collapses_repeats(sqlite_client: AsyncClient) -> None:
    ctx = await _setup(sqlite_client)
    base_id = await _experiment(
        sqlite_client, ctx, "base", [["yes"] * N_REPEATS for _ in range(N_ITEMS)]
    )
    cand_id = await _experiment(
        sqlite_client,
        ctx,
        "cand",
        [["no", "no", "yes"]] + [["yes"] * N_REPEATS for _ in range(N_ITEMS - 1)],
    )
    items = (
        await sqlite_client.get(f"/api/v1/experiments/{cand_id}/compare/{base_id}/items")
    ).json()
    first = next(row for row in items["items"] if row["dataset_item_id"] == ctx["item_ids"][0])
    assert first["candidate"]["score"] == pytest.approx(1 / 3)
    assert first["candidate"]["label"] == "FAIL"
    assert first["candidate"]["metadata"]["repeats"]["flaky"] is True
    assert first["baseline"]["score"] == pytest.approx(1.0)

    compare = (await sqlite_client.get(f"/api/v1/experiments/{cand_id}/compare/{base_id}")).json()
    mean = next(m for m in compare["metrics"] if m["metric"] == "mean_score")
    assert mean["n_paired"] == N_ITEMS


@pytest.mark.asyncio
async def test_client_results_accept_repeats(sqlite_client: AsyncClient) -> None:
    ctx = await _setup(sqlite_client)
    exp_id = await _experiment(sqlite_client, ctx, "cand", [["yes", "yes"] for _ in range(N_ITEMS)])
    results = [
        {"dataset_item_id": item_id, "repeat": repeat, "score": float(repeat)}
        for item_id in ctx["item_ids"]
        for repeat in range(2)
    ]
    resp = await sqlite_client.post(
        f"/api/v1/experiments/{exp_id}/client-results",
        json={"metrics": [{"name": "local", "threshold": 0.5, "results": results}]},
    )
    assert resp.status_code == 201, resp.text
    summary = (await sqlite_client.get(f"/api/v1/experiments/{exp_id}/summary")).json()
    local = next(r for r in summary["evaluators"] if r["evaluator_name"] == "local")
    assert local["mean_score"] == pytest.approx(0.5)
    assert local["n_flaky"] == N_ITEMS

    dup = await sqlite_client.post(
        f"/api/v1/experiments/{exp_id}/client-results",
        json={"metrics": [{"name": "local", "results": [results[0], results[0]]}]},
    )
    assert dup.status_code == 400

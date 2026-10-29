"""Per-group analysis (``group_by`` on dataset-item metadata) for summary, compare, gate."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx2 import AsyncClient

import test_sqlite_smoke
from opengrade_server.domain.dataset import DatasetItem
from opengrade_server.regression.groups import NO_VALUE, InvalidGroupKeyError, item_groups
from opengrade_server.regression.policy import InvalidPolicyError, parse_release_policy

sqlite_client = test_sqlite_smoke.sqlite_client


def _item(metadata: dict[str, Any]) -> DatasetItem:
    return DatasetItem(
        id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        input="q",
        expected_output=None,
        actual_output=None,
        context=None,
        metadata=metadata,
    )


def test_item_groups_values_lists_nested_and_missing() -> None:
    a = _item({"category": "billing"})
    b = _item({"category": 3})
    c = _item({"tags": ["x", "y"]})
    d = _item({"meta": {"lang": "it"}})
    e = _item({})
    assert item_groups([a, b, c, d, e], "category") == {
        NO_VALUE: {c.id, d.id, e.id},
        "3": {b.id},
        "billing": {a.id},
    }
    assert item_groups([c], "tags") == {"x": {c.id}, "y": {c.id}}
    assert item_groups([d, e], "meta.lang") == {NO_VALUE: {e.id}, "it": {d.id}}
    with pytest.raises(InvalidGroupKeyError):
        item_groups([a], "bad key!")
    with pytest.raises(InvalidGroupKeyError, match="distinct values"):
        item_groups([_item({"id": i}) for i in range(60)], "id")


def test_parse_groups_policy() -> None:
    policy = parse_release_policy(
        {"exact": {"min": 0.8}, "groups": {"by": "category", "min_items": 3}}
    )
    assert policy.groups is not None
    assert policy.groups.by == "category"
    assert policy.groups.min_items == 3
    with pytest.raises(InvalidPolicyError, match="requires by"):
        parse_release_policy({"exact": {"min": 0.8}, "groups": {}})
    with pytest.raises(InvalidPolicyError, match="unsupported keys"):
        parse_release_policy({"exact": {"min": 0.8}, "groups": {"by": "c", "x": 1}})
    with pytest.raises(InvalidPolicyError, match="per group"):
        parse_release_policy({"latency": {"p95_max_ms": 10}, "groups": {"by": "c"}})


CATEGORIES = ["billing"] * 6 + ["shipping"] * 6


async def _setup(client: AsyncClient) -> dict[str, Any]:
    project = (await client.post("/api/v1/projects", json={"name": "Groups"})).json()
    dataset = (
        await client.post(
            f"/api/v1/projects/{project['id']}/datasets",
            json={"name": "gold", "task_type": "classification"},
        )
    ).json()
    item_ids = []
    for i, category in enumerate(CATEGORIES):
        item = await client.post(
            f"/api/v1/datasets/{dataset['id']}/items",
            json={"input": f"q{i}", "expected_output": "yes", "metadata": {"category": category}},
        )
        assert item.status_code == 201, item.text
        item_ids.append(item.json()["id"])
    evaluator = await client.post(
        f"/api/v1/projects/{project['id']}/evaluators",
        json={"name": "exact", "type": "deterministic", "config": {"kind": "exact_match"}},
    )
    return {
        "project_id": project["id"],
        "dataset_id": dataset["id"],
        "item_ids": item_ids,
        "evaluator_id": evaluator.json()["id"],
    }


async def _experiment(client: AsyncClient, ctx: dict[str, Any], name: str, wrong: set[int]) -> str:
    exp = (
        await client.post(
            f"/api/v1/projects/{ctx['project_id']}/experiments",
            json={"name": name, "dataset_id": ctx["dataset_id"]},
        )
    ).json()
    items = [
        {"dataset_item_id": item_id, "actual_output": "no" if i in wrong else "yes"}
        for i, item_id in enumerate(ctx["item_ids"])
    ]
    put = await client.put(f"/api/v1/experiments/{exp['id']}/outputs", json={"items": items})
    assert put.status_code == 200, put.text
    evaluated = await client.post(
        f"/api/v1/experiments/{exp['id']}/evaluate",
        json={"evaluator_ids": [ctx["evaluator_id"]]},
    )
    assert evaluated.status_code == 202, evaluated.text
    return str(exp["id"])


@pytest.mark.asyncio
async def test_group_by_summary_compare_and_gate(sqlite_client: AsyncClient) -> None:
    ctx = await _setup(sqlite_client)
    base_id = await _experiment(sqlite_client, ctx, "base", wrong=set())
    # Shipping (items 6..11) loses 3 of 6; billing stays perfect. Global mean 0.75.
    cand_id = await _experiment(sqlite_client, ctx, "cand", wrong={6, 7, 8})

    summary = (
        await sqlite_client.get(
            f"/api/v1/experiments/{cand_id}/summary", params={"group_by": "category"}
        )
    ).json()
    assert summary["group_by"] == "category"
    by_value = {g["value"]: g for g in summary["groups"]}
    assert set(by_value) == {"billing", "shipping"}
    assert by_value["billing"]["evaluators"][0]["mean_score"] == pytest.approx(1.0)
    assert by_value["shipping"]["evaluators"][0]["mean_score"] == pytest.approx(0.5)
    assert by_value["shipping"]["n_items"] == 6

    compare = (
        await sqlite_client.get(
            f"/api/v1/experiments/{cand_id}/compare/{base_id}", params={"group_by": "category"}
        )
    ).json()
    groups = {g["value"]: g for g in compare["groups"]}
    shipping = next(m for m in groups["shipping"]["metrics"] if m["metric"] == "mean_score")
    assert shipping["delta"] == pytest.approx(-0.5)
    billing = next(m for m in groups["billing"]["metrics"] if m["metric"] == "mean_score")
    assert billing["delta"] == pytest.approx(0.0)
    assert billing["status"] == "unchanged"

    url = f"/api/v1/projects/{ctx['project_id']}/release-check"
    flat = {"exact": {"min": 0.7}}
    passed = await sqlite_client.post(url, json={"experiment_id": cand_id, "policy": flat})
    assert passed.json()["status"] == "passed", passed.text

    grouped = await sqlite_client.post(
        url,
        json={
            "experiment_id": cand_id,
            "baseline_experiment_id": base_id,
            "policy": {
                **flat,
                "regression": {"max_delta": -0.3},
                "groups": {"by": "category", "min_items": 5},
            },
        },
    )
    assert grouped.status_code == 200, grouped.text
    body = grouped.json()
    assert body["status"] == "failed"
    checks = {c["metric"]: c for c in body["checks"]}
    assert checks["groups.category=shipping.exact.min"]["status"] == "failed"
    assert checks["groups.category=billing.exact.min"]["status"] == "passed"
    assert checks["groups.category=shipping.regression.exact.mean_score"]["status"] == "failed"
    assert checks["regression.exact.mean_score"]["status"] == "passed"

    small = await sqlite_client.post(
        url,
        json={
            "experiment_id": cand_id,
            "policy": {**flat, "groups": {"by": "category", "min_items": 10}},
        },
    )
    assert small.json()["status"] == "passed"
    assert not any(c["metric"].startswith("groups.") for c in small.json()["checks"])


@pytest.mark.asyncio
async def test_group_by_rejects_bad_key(sqlite_client: AsyncClient) -> None:
    ctx = await _setup(sqlite_client)
    exp_id = await _experiment(sqlite_client, ctx, "cand", wrong=set())
    bad = await sqlite_client.get(
        f"/api/v1/experiments/{exp_id}/summary", params={"group_by": "no spaces"}
    )
    assert bad.status_code == 400

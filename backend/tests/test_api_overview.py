from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from aiobs.application.compare import CompareExperiments
from aiobs.evaluation import bootstrap_evaluators
from aiobs.evaluation.registry import clear_registry
from support.fake_llm import ScriptedJudgeLlm

pytestmark = pytest.mark.integration


def _use_fake_judge_llm() -> None:
    clear_registry()
    bootstrap_evaluators(ScriptedJudgeLlm())


def _series_bucket_step_seconds(series: list[dict]) -> float:
    assert len(series) >= 2
    starts = [datetime.fromisoformat(b["bucket_start"].replace("Z", "+00:00")) for b in series]
    return (starts[1] - starts[0]).total_seconds()


@pytest.mark.asyncio
async def test_overview_unknown_project_404(client: AsyncClient) -> None:
    since = datetime.now(tz=UTC) - timedelta(hours=24)
    resp = await client.get(
        "/api/v1/projects/00000000-0000-0000-0000-000000000000/overview",
        params={"since": since.isoformat()},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_overview_empty_project(client: AsyncClient) -> None:
    created = await client.post(
        "/api/v1/projects",
        json={"name": "Ov", "slug": f"ov-{uuid.uuid4().hex[:8]}"},
    )
    assert created.status_code == 201
    pid = created.json()["id"]
    since = datetime.now(tz=UTC) - timedelta(hours=24)
    resp = await client.get(
        f"/api/v1/projects/{pid}/overview",
        params={"since": since.isoformat()},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["live"]["n_interactions"] == 0
    assert body["offline"]["n_datasets"] == 0
    assert body["offline"]["compare"] is None
    assert "generated_at" in body


@pytest.mark.asyncio
async def test_overview_live_only_in_range(client: AsyncClient) -> None:
    project = await client.post(
        "/api/v1/projects",
        json={"name": "Live Ov", "slug": f"live-ov-{uuid.uuid4().hex[:8]}"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    ensure = await client.post(f"/api/v1/projects/{project_id}/metrics-pack/ensure")
    assert ensure.status_code == 200, ensure.text

    submit = await client.post(
        f"/api/v1/projects/{project_id}/live-interactions",
        json={
            "question": "What is PTO?",
            "answer": "Paid time off",
            "documents": [{"id": "doc-1", "text": "PTO means paid time off"}],
        },
    )
    assert submit.status_code == 202
    interaction_id = submit.json()["id"]

    _use_fake_judge_llm()
    scored = await client.post(f"/api/v1/live-interactions/{interaction_id}/rescore")
    assert scored.status_code == 200
    assert scored.json()["judge_status"] == "scored"
    assert scored.json()["scores"]

    since = datetime.now(tz=UTC) - timedelta(hours=24)
    resp = await client.get(
        f"/api/v1/projects/{project_id}/overview",
        params={"since": since.isoformat()},
    )
    assert resp.status_code == 200
    live = resp.json()["live"]
    assert live["n_interactions"] == 1
    assert live["mean_score"] is not None
    assert len(live["series"]) >= 1


@pytest.mark.asyncio
async def test_overview_offline_compare_with_baseline(client: AsyncClient) -> None:
    project = await client.post(
        "/api/v1/projects",
        json={"name": "Compare Ov", "slug": f"cmp-ov-{uuid.uuid4().hex[:8]}"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    dataset = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "shared", "task_type": "classification"},
    )
    assert dataset.status_code == 201
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
    assert evaluator.status_code == 201
    evaluator_id = evaluator.json()["id"]

    baseline = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "baseline", "dataset_id": dataset_id},
    )
    assert baseline.status_code == 201
    baseline_id = baseline.json()["id"]

    candidate = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={
            "name": "candidate",
            "dataset_id": dataset_id,
            "baseline_experiment_id": baseline_id,
        },
    )
    assert candidate.status_code == 201
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

    since = datetime.now(tz=UTC) - timedelta(hours=24)
    resp = await client.get(
        f"/api/v1/projects/{project_id}/overview",
        params={"since": since.isoformat()},
    )
    assert resp.status_code == 200
    offline = resp.json()["offline"]
    assert offline["compare"] is not None
    assert offline["compare"]["candidate_experiment_id"] == candidate_id
    assert offline["compare"]["baseline_experiment_id"] == baseline_id
    metrics = offline["compare"]["metrics"]
    assert metrics
    assert metrics[0]["metric"] == "pass_rate"
    assert metrics[0]["status"] == "regressed"
    assert offline["regressions"]
    assert offline["regressions"][0]["status"] == "regressed"


@pytest.mark.asyncio
async def test_overview_compare_failure_degraded(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _compare_raises(self: CompareExperiments, *args: object, **kwargs: object) -> None:
        raise RuntimeError("compare unavailable")

    monkeypatch.setattr(CompareExperiments, "execute", _compare_raises)

    project = await client.post(
        "/api/v1/projects",
        json={"name": "Compare Fail", "slug": f"cmp-fail-{uuid.uuid4().hex[:8]}"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    dataset = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "shared", "task_type": "classification"},
    )
    assert dataset.status_code == 201
    dataset_id = dataset.json()["id"]
    for idx in range(2):
        item = await client.post(
            f"/api/v1/datasets/{dataset_id}/items",
            json={
                "input": f"q{idx}",
                "expected_output": "a",
                "actual_output": "a",
            },
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

    baseline = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "baseline", "dataset_id": dataset_id},
    )
    assert baseline.status_code == 201
    baseline_id = baseline.json()["id"]

    candidate = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={
            "name": "candidate",
            "dataset_id": dataset_id,
            "baseline_experiment_id": baseline_id,
        },
    )
    assert candidate.status_code == 201
    candidate_id = candidate.json()["id"]

    for experiment_id in (baseline_id, candidate_id):
        evaluated = await client.post(
            f"/api/v1/experiments/{experiment_id}/evaluate",
            json={"evaluator_ids": [evaluator_id]},
        )
        assert evaluated.status_code == 200

    since = datetime.now(tz=UTC) - timedelta(hours=24)
    resp = await client.get(
        f"/api/v1/projects/{project_id}/overview",
        params={"since": since.isoformat()},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["offline"]["compare"] is None
    assert body["offline"]["latest_experiment"]["id"] == candidate_id
    assert "compare_unavailable" in body["warnings"]


@pytest.mark.asyncio
async def test_overview_no_baseline_compare_null(client: AsyncClient) -> None:
    project = await client.post(
        "/api/v1/projects",
        json={"name": "Solo", "slug": f"solo-{uuid.uuid4().hex[:8]}"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    dataset = await client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "ds", "task_type": "classification"},
    )
    dataset_id = dataset.json()["id"]
    await client.post(
        f"/api/v1/datasets/{dataset_id}/items",
        json={"input": "q", "expected_output": "a", "actual_output": "a"},
    )

    evaluator = await client.post(
        f"/api/v1/projects/{project_id}/evaluators",
        json={
            "name": "exact",
            "type": "deterministic",
            "config": {"kind": "exact_match"},
        },
    )
    evaluator_id = evaluator.json()["id"]

    experiment = await client.post(
        f"/api/v1/projects/{project_id}/experiments",
        json={"name": "only", "dataset_id": dataset_id},
    )
    experiment_id = experiment.json()["id"]
    evaluated = await client.post(
        f"/api/v1/experiments/{experiment_id}/evaluate",
        json={"evaluator_ids": [evaluator_id]},
    )
    assert evaluated.status_code == 200

    since = datetime.now(tz=UTC) - timedelta(hours=24)
    resp = await client.get(
        f"/api/v1/projects/{project_id}/overview",
        params={"since": since.isoformat()},
    )
    assert resp.status_code == 200
    offline = resp.json()["offline"]
    assert offline["latest_experiment"]["id"] == experiment_id
    assert offline["compare"] is None


@pytest.mark.asyncio
async def test_overview_empty_time_range_zeros(client: AsyncClient) -> None:
    project = await client.post(
        "/api/v1/projects",
        json={"name": "Range", "slug": f"range-{uuid.uuid4().hex[:8]}"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    ensure = await client.post(f"/api/v1/projects/{project_id}/metrics-pack/ensure")
    assert ensure.status_code == 200

    submit = await client.post(
        f"/api/v1/projects/{project_id}/live-interactions",
        json={"question": "q", "answer": "a", "documents": []},
    )
    assert submit.status_code == 202
    interaction_id = submit.json()["id"]
    _use_fake_judge_llm()
    scored = await client.post(f"/api/v1/live-interactions/{interaction_id}/rescore")
    assert scored.status_code == 200

    future = datetime.now(tz=UTC) + timedelta(days=1)
    since = future
    until = future + timedelta(hours=1)
    resp = await client.get(
        f"/api/v1/projects/{project_id}/overview",
        params={"since": since.isoformat(), "until": until.isoformat()},
    )
    assert resp.status_code == 200
    assert resp.json()["live"]["n_interactions"] == 0
    assert resp.json()["live"]["series"] == []


@pytest.mark.asyncio
async def test_overview_bucket_spacing_shorter_window_is_denser(client: AsyncClient) -> None:
    project = await client.post(
        "/api/v1/projects",
        json={"name": "Buckets", "slug": f"bucket-{uuid.uuid4().hex[:8]}"},
    )
    assert project.status_code == 201
    project_id = project.json()["id"]

    ensure = await client.post(f"/api/v1/projects/{project_id}/metrics-pack/ensure")
    assert ensure.status_code == 200

    submit = await client.post(
        f"/api/v1/projects/{project_id}/live-interactions",
        json={
            "question": "bucket test",
            "answer": "answer",
            "documents": [{"id": "d1", "text": "context"}],
        },
    )
    assert submit.status_code == 202
    interaction_id = submit.json()["id"]
    _use_fake_judge_llm()
    scored = await client.post(f"/api/v1/live-interactions/{interaction_id}/rescore")
    assert scored.status_code == 200

    now = datetime.now(tz=UTC)
    short_since = now - timedelta(hours=1)
    short = await client.get(
        f"/api/v1/projects/{project_id}/overview",
        params={"since": short_since.isoformat(), "until": now.isoformat()},
    )
    assert short.status_code == 200
    short_series = short.json()["live"]["series"]
    assert len(short_series) >= 2
    short_step = _series_bucket_step_seconds(short_series)

    long_since = now - timedelta(days=7)
    long = await client.get(
        f"/api/v1/projects/{project_id}/overview",
        params={"since": long_since.isoformat(), "until": now.isoformat()},
    )
    assert long.status_code == 200
    long_series = long.json()["live"]["series"]
    assert len(long_series) >= 2
    long_step = _series_bucket_step_seconds(long_series)

    assert short_step < long_step
    assert short_step == pytest.approx(300.0)
    assert long_step == pytest.approx(6 * 3600.0)

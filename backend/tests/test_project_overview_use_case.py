from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from aiobs_server.application.compare import CompareExperiments
from aiobs_server.application.live_judge_calibration import SummarizeLiveJudgeCalibration
from aiobs_server.application.project_overview import GetProjectOverview
from aiobs_server.application.projects import ProjectNotFoundError
from aiobs_server.domain.dataset import Dataset
from aiobs_server.domain.evaluation import EvaluationResultRecord, EvaluationRun
from aiobs_server.domain.evaluator import Evaluator
from aiobs_server.domain.experiment import Experiment
from aiobs_server.domain.live_interaction import LiveInteraction, LiveInteractionScore
from aiobs_server.domain.live_overview import LiveInRangeResult, LiveInteractionInRange
from aiobs_server.domain.project import Project


class InMemoryProjectRepository:
    def __init__(self) -> None:
        self._projects: dict[uuid.UUID, Project] = {}

    async def add(self, project: Project) -> Project:
        self._projects[project.id] = project
        return project

    async def get_by_id(self, project_id: uuid.UUID) -> Project | None:
        return self._projects.get(project_id)


class InMemoryDatasetRepository:
    def __init__(self) -> None:
        self._datasets: dict[uuid.UUID, Dataset] = {}

    async def add(self, dataset: Dataset) -> Dataset:
        self._datasets[dataset.id] = dataset
        return dataset

    async def list_by_project(self, project_id: uuid.UUID, **kwargs: object) -> list[Dataset]:
        return [d for d in self._datasets.values() if d.project_id == project_id]


class InMemoryMetricsSetRepository:
    async def get_project_default(self, project_id: uuid.UUID) -> None:
        return None


class InMemoryExperimentRepository:
    def __init__(self) -> None:
        self._items: dict[uuid.UUID, Experiment] = {}

    async def add(self, experiment: Experiment) -> Experiment:
        self._items[experiment.id] = experiment
        return experiment

    async def get_by_id(self, experiment_id: uuid.UUID) -> Experiment | None:
        return self._items.get(experiment_id)

    async def list_by_project(self, project_id: uuid.UUID) -> list[Experiment]:
        rows = [e for e in self._items.values() if e.project_id == project_id]
        rows.sort(key=lambda e: e.created_at, reverse=True)
        return rows


class InMemoryEvaluationRunRepository:
    def __init__(self) -> None:
        self._runs: dict[uuid.UUID, EvaluationRun] = {}
        self._results: dict[uuid.UUID, EvaluationResultRecord] = {}

    async def list_runs_by_experiment(self, experiment_id: uuid.UUID) -> list[EvaluationRun]:
        return [r for r in self._runs.values() if r.experiment_id == experiment_id]

    async def list_results(self, run_id: uuid.UUID) -> list[EvaluationResultRecord]:
        return [r for r in self._results.values() if r.run_id == run_id]

    async def add_run(self, run: EvaluationRun) -> EvaluationRun:
        self._runs[run.id] = run
        return run

    async def add_result(self, result: EvaluationResultRecord) -> EvaluationResultRecord:
        self._results[result.id] = result
        return result


class InMemoryEvaluatorRepository:
    def __init__(self) -> None:
        self._items: dict[uuid.UUID, Evaluator] = {}

    async def add(self, evaluator: Evaluator) -> Evaluator:
        self._items[evaluator.id] = evaluator
        return evaluator

    async def get_by_ids(self, evaluator_ids: list[uuid.UUID]) -> list[Evaluator]:
        return [self._items[i] for i in evaluator_ids if i in self._items]


class InMemoryLiveRepository:
    def __init__(self) -> None:
        self._items: dict[uuid.UUID, LiveInteraction] = {}
        self._scores: dict[uuid.UUID, list[LiveInteractionScore]] = {}

    async def add_with_scores(
        self,
        interaction: LiveInteraction,
        scores: list[LiveInteractionScore],
    ) -> None:
        self._items[interaction.id] = interaction
        self._scores[interaction.id] = list(scores)

    async def list_in_range(
        self,
        project_id: uuid.UUID,
        *,
        since: datetime,
        until: datetime,
        limit: int = 10_000,
    ) -> LiveInRangeResult:
        cap = max(1, min(limit, 10_000))
        rows = [
            i
            for i in self._items.values()
            if i.project_id == project_id and since <= i.created_at < until
        ]
        rows.sort(key=lambda i: (i.created_at, i.id), reverse=True)
        truncated = len(rows) > cap
        out: list[LiveInteractionInRange] = []
        for interaction in rows[:cap]:
            out.append(
                LiveInteractionInRange(
                    interaction=interaction,
                    scores=list(self._scores.get(interaction.id, [])),
                )
            )
        return LiveInRangeResult(items=out, truncated=truncated)

    async def list_calibration_rows(
        self,
        project_id: uuid.UUID,
        *,
        since: datetime,
    ) -> list:
        return []


def _build_use_case(
    *,
    projects: InMemoryProjectRepository,
    datasets: InMemoryDatasetRepository | None = None,
    experiments: InMemoryExperimentRepository | None = None,
    live: InMemoryLiveRepository | None = None,
    runs: InMemoryEvaluationRunRepository | None = None,
    evaluators: InMemoryEvaluatorRepository | None = None,
) -> GetProjectOverview:
    datasets = datasets or InMemoryDatasetRepository()
    experiments = experiments or InMemoryExperimentRepository()
    live = live or InMemoryLiveRepository()
    runs = runs or InMemoryEvaluationRunRepository()
    evaluators = evaluators or InMemoryEvaluatorRepository()
    return GetProjectOverview(
        projects=projects,
        datasets=datasets,
        metrics_sets=InMemoryMetricsSetRepository(),
        experiments=experiments,
        live=live,
        compare=CompareExperiments(experiments, runs, evaluators),
        calibration=SummarizeLiveJudgeCalibration(projects, live),
    )


@pytest.mark.asyncio
async def test_empty_project_overview() -> None:
    projects = InMemoryProjectRepository()
    project = Project.create("Empty")
    await projects.add(project)
    since = datetime(2026, 10, 9, 0, 0, tzinfo=UTC)
    until = since + timedelta(hours=24)
    use_case = _build_use_case(projects=projects)
    result = await use_case.execute(project.id, since=since, until=until)
    assert result.live.n_interactions == 0
    assert result.live.series == []
    assert result.offline.n_datasets == 0
    assert result.offline.metrics_set is None
    assert result.offline.latest_experiment is None
    assert result.offline.release_ready is False
    assert result.offline.compare is None
    assert result.offline.regressions == []


@pytest.mark.asyncio
async def test_unknown_project_raises() -> None:
    since = datetime(2026, 10, 9, 0, 0, tzinfo=UTC)
    until = since + timedelta(hours=24)
    use_case = _build_use_case(projects=InMemoryProjectRepository())
    with pytest.raises(ProjectNotFoundError):
        await use_case.execute(uuid.uuid4(), since=since, until=until)


@pytest.mark.asyncio
async def test_live_interactions_in_range() -> None:
    projects = InMemoryProjectRepository()
    project = Project.create("Live")
    await projects.add(project)
    live = InMemoryLiveRepository()
    since = datetime(2026, 10, 9, 10, 0, tzinfo=UTC)
    until = since + timedelta(hours=24)
    t1 = since + timedelta(hours=2)
    t2 = since + timedelta(hours=5)
    i1 = replace(
        LiveInteraction.create(project.id, "q1", "a1").with_status("scored"),
        created_at=t1,
    )
    i2 = replace(
        LiveInteraction.create(project.id, "q2", "a2").with_status("scored"),
        created_at=t2,
    )
    s1 = LiveInteractionScore.create(i1.id, "groundedness", score=0.8, label="PASS", threshold=0.7)
    s2 = LiveInteractionScore.create(i2.id, "groundedness", score=0.3, label="FAIL", threshold=0.7)
    await live.add_with_scores(i1, [s1])
    await live.add_with_scores(i2, [s2])
    use_case = _build_use_case(projects=projects, live=live)
    result = await use_case.execute(project.id, since=since, until=until)
    assert result.live.n_interactions == 2
    assert result.live.n_failed == 1
    assert result.live.mean_score == pytest.approx(0.55)
    assert result.live.fail_rate == pytest.approx(0.5)
    assert len(result.live.series) >= 1
    assert len(result.live.attention) == 1
    assert result.live.attention[0].interaction_id == i2.id


@pytest.mark.asyncio
async def test_empty_time_range() -> None:
    projects = InMemoryProjectRepository()
    project = Project.create("Range")
    await projects.add(project)
    live = InMemoryLiveRepository()
    since = datetime(2026, 10, 9, 10, 0, tzinfo=UTC)
    until = since + timedelta(hours=24)
    outside = since - timedelta(hours=1)
    interaction = replace(
        LiveInteraction.create(project.id, "old", "a").with_status("scored"),
        created_at=outside,
    )
    await live.add_with_scores(interaction, [])
    use_case = _build_use_case(projects=projects, live=live)
    result = await use_case.execute(project.id, since=since, until=until)
    assert result.live.n_interactions == 0
    assert result.live.series == []


@pytest.mark.asyncio
async def test_latest_without_baseline_no_compare() -> None:
    projects = InMemoryProjectRepository()
    project = Project.create("No baseline")
    await projects.add(project)
    experiments = InMemoryExperimentRepository()
    dataset_id = uuid.uuid4()
    exp = Experiment.create(
        project.id,
        "solo",
        dataset_id,
        status="completed",
    )
    await experiments.add(exp)
    since = datetime(2026, 10, 9, 0, 0, tzinfo=UTC)
    until = since + timedelta(hours=24)
    use_case = _build_use_case(projects=projects, experiments=experiments)
    result = await use_case.execute(project.id, since=since, until=until)
    assert result.offline.latest_experiment is not None
    assert result.offline.latest_experiment.id == exp.id
    assert result.offline.release_ready is True
    assert result.offline.compare is None


@pytest.mark.asyncio
async def test_latest_with_baseline_compare_and_regressions() -> None:
    projects = InMemoryProjectRepository()
    project = Project.create("Compare")
    await projects.add(project)
    dataset_id = uuid.uuid4()
    evaluator_id = uuid.uuid4()
    evaluators = InMemoryEvaluatorRepository()
    ev = Evaluator.create(
        project.id,
        "exact",
        "deterministic",
        {"kind": "exact_match"},
    )
    ev = replace(ev, id=evaluator_id)
    await evaluators.add(ev)
    experiments = InMemoryExperimentRepository()
    baseline = Experiment.create(project.id, "baseline", dataset_id, status="completed")
    candidate = replace(
        Experiment.create(
            project.id,
            "candidate",
            dataset_id,
            baseline_experiment_id=baseline.id,
            status="completed",
        ),
        created_at=baseline.created_at + timedelta(seconds=1),
    )
    await experiments.add(baseline)
    await experiments.add(candidate)
    runs = InMemoryEvaluationRunRepository()
    base_run = EvaluationRun.create(baseline.id, evaluator_id, status="PASSED")
    cand_run = EvaluationRun.create(candidate.id, evaluator_id, status="PASSED")
    await runs.add_run(base_run)
    await runs.add_run(cand_run)
    for _ in range(5):
        await runs.add_result(
            EvaluationResultRecord.create(
                base_run.id,
                dataset_item_id=uuid.uuid4(),
                score=1.0,
                label="PASS",
            )
        )
        await runs.add_result(
            EvaluationResultRecord.create(
                cand_run.id,
                dataset_item_id=uuid.uuid4(),
                score=0.0,
                label="FAIL",
            )
        )
    since = datetime(2026, 10, 9, 0, 0, tzinfo=UTC)
    until = since + timedelta(hours=24)
    use_case = _build_use_case(
        projects=projects,
        experiments=experiments,
        runs=runs,
        evaluators=evaluators,
    )
    result = await use_case.execute(project.id, since=since, until=until)
    assert result.offline.compare is not None
    assert result.offline.compare.candidate_experiment_id == candidate.id
    assert result.offline.compare.baseline_experiment_id == baseline.id
    pass_rows = [m for m in result.offline.compare.metrics if m.metric == "pass_rate"]
    assert len(pass_rows) == 1
    assert pass_rows[0].status == "regressed"
    assert len(result.offline.regressions) == 1
    assert result.offline.regressions[0].status == "regressed"


@pytest.mark.asyncio
async def test_live_truncated_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    projects = InMemoryProjectRepository()
    project = Project.create("Truncated")
    await projects.add(project)
    live = InMemoryLiveRepository()
    since = datetime(2026, 10, 9, 0, 0, tzinfo=UTC)
    until = since + timedelta(hours=24)
    for idx in range(10_001):
        t = since + timedelta(seconds=idx)
        interaction = replace(
            LiveInteraction.create(project.id, f"q{idx}", "a").with_status("scored"),
            created_at=t,
        )
        await live.add_with_scores(interaction, [])
    use_case = _build_use_case(projects=projects, live=live)
    result = await use_case.execute(project.id, since=since, until=until)
    assert result.live.n_interactions == 10_000
    assert "live_truncated" in result.warnings


@pytest.mark.asyncio
async def test_calibration_failure_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _cal_raises(
        self: SummarizeLiveJudgeCalibration, *args: object, **kwargs: object
    ) -> None:
        raise RuntimeError("calibration unavailable")

    monkeypatch.setattr(SummarizeLiveJudgeCalibration, "execute", _cal_raises)

    projects = InMemoryProjectRepository()
    project = Project.create("Cal fail")
    await projects.add(project)
    since = datetime(2026, 10, 9, 0, 0, tzinfo=UTC)
    until = since + timedelta(hours=24)
    use_case = _build_use_case(projects=projects)
    result = await use_case.execute(project.id, since=since, until=until)
    assert result.calibration_alerts == []
    assert "calibration_unavailable" in result.warnings

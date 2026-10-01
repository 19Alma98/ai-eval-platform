from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from aiobs.application.datasets import (
    AddDatasetItem,
    AddDatasetItemFromTrace,
    CreateDataset,
    GetDataset,
    ListDatasets,
)
from aiobs.application.evaluate import (
    EvaluateExperiment,
    GetEvaluationRun,
    ListExperimentRuns,
)
from aiobs.application.evaluators import CreateEvaluator, ListEvaluators
from aiobs.application.experiments import (
    CreateExperiment,
    GetExperiment,
    ListExperiments,
)
from aiobs.application.projects import CreateProject, GetProject, ListProjects
from aiobs.application.traces import (
    CreateTrace,
    GetTrace,
    IngestNormalizedTraces,
    ListTraces,
    ResolveProject,
)
from aiobs.config import Settings, get_settings
from aiobs.evaluation.runner import EvaluationRunner
from aiobs.infrastructure.db import get_session
from aiobs.infrastructure.repositories import (
    SqlAlchemyDatasetRepository,
    SqlAlchemyEvaluationRunRepository,
    SqlAlchemyEvaluatorRepository,
    SqlAlchemyExperimentRepository,
    SqlAlchemyProjectRepository,
    SqlAlchemyTraceRepository,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_session():
        yield session


def get_project_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SqlAlchemyProjectRepository:
    return SqlAlchemyProjectRepository(session)


def get_trace_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SqlAlchemyTraceRepository:
    return SqlAlchemyTraceRepository(session)


def get_dataset_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SqlAlchemyDatasetRepository:
    return SqlAlchemyDatasetRepository(session)


def get_evaluator_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SqlAlchemyEvaluatorRepository:
    return SqlAlchemyEvaluatorRepository(session)


def get_experiment_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SqlAlchemyExperimentRepository:
    return SqlAlchemyExperimentRepository(session)


def get_evaluation_run_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SqlAlchemyEvaluationRunRepository:
    return SqlAlchemyEvaluationRunRepository(session)


def get_create_project(
    repository: SqlAlchemyProjectRepository = Depends(get_project_repository),
) -> CreateProject:
    return CreateProject(repository)


def get_list_projects(
    repository: SqlAlchemyProjectRepository = Depends(get_project_repository),
) -> ListProjects:
    return ListProjects(repository)


def get_get_project(
    repository: SqlAlchemyProjectRepository = Depends(get_project_repository),
) -> GetProject:
    return GetProject(repository)


def get_ingest_traces(
    repository: SqlAlchemyTraceRepository = Depends(get_trace_repository),
) -> IngestNormalizedTraces:
    return IngestNormalizedTraces(repository)


def get_create_trace(
    repository: SqlAlchemyTraceRepository = Depends(get_trace_repository),
) -> CreateTrace:
    return CreateTrace(repository)


def get_list_traces(
    repository: SqlAlchemyTraceRepository = Depends(get_trace_repository),
) -> ListTraces:
    return ListTraces(repository)


def get_get_trace(
    repository: SqlAlchemyTraceRepository = Depends(get_trace_repository),
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
) -> GetTrace:
    return GetTrace(repository, projects)


def get_resolve_project(
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
) -> ResolveProject:
    return ResolveProject(projects)


def get_create_dataset(
    datasets: SqlAlchemyDatasetRepository = Depends(get_dataset_repository),
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
) -> CreateDataset:
    return CreateDataset(datasets, projects)


def get_list_datasets(
    datasets: SqlAlchemyDatasetRepository = Depends(get_dataset_repository),
) -> ListDatasets:
    return ListDatasets(datasets)


def get_get_dataset(
    datasets: SqlAlchemyDatasetRepository = Depends(get_dataset_repository),
) -> GetDataset:
    return GetDataset(datasets)


def get_add_dataset_item(
    datasets: SqlAlchemyDatasetRepository = Depends(get_dataset_repository),
) -> AddDatasetItem:
    return AddDatasetItem(datasets)


def get_add_dataset_item_from_trace(
    datasets: SqlAlchemyDatasetRepository = Depends(get_dataset_repository),
    traces: SqlAlchemyTraceRepository = Depends(get_trace_repository),
) -> AddDatasetItemFromTrace:
    return AddDatasetItemFromTrace(datasets, traces)


def get_create_evaluator(
    evaluators: SqlAlchemyEvaluatorRepository = Depends(get_evaluator_repository),
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
) -> CreateEvaluator:
    return CreateEvaluator(evaluators, projects)


def get_list_evaluators(
    evaluators: SqlAlchemyEvaluatorRepository = Depends(get_evaluator_repository),
) -> ListEvaluators:
    return ListEvaluators(evaluators)


def get_create_experiment(
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
    datasets: SqlAlchemyDatasetRepository = Depends(get_dataset_repository),
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
) -> CreateExperiment:
    return CreateExperiment(experiments, datasets, projects)


def get_list_experiments(
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
) -> ListExperiments:
    return ListExperiments(experiments)


def get_get_experiment(
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
) -> GetExperiment:
    return GetExperiment(experiments)


def get_app_settings() -> Settings:
    return get_settings()


def get_evaluation_runner(
    settings: Settings = Depends(get_app_settings),
) -> EvaluationRunner:
    return EvaluationRunner(max_concurrency=settings.llm_max_concurrency)


def get_evaluate_experiment(
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
    datasets: SqlAlchemyDatasetRepository = Depends(get_dataset_repository),
    evaluators: SqlAlchemyEvaluatorRepository = Depends(get_evaluator_repository),
    runs: SqlAlchemyEvaluationRunRepository = Depends(get_evaluation_run_repository),
    runner: EvaluationRunner = Depends(get_evaluation_runner),
) -> EvaluateExperiment:
    return EvaluateExperiment(experiments, datasets, evaluators, runs, runner)


def get_list_experiment_runs(
    runs: SqlAlchemyEvaluationRunRepository = Depends(get_evaluation_run_repository),
) -> ListExperimentRuns:
    return ListExperimentRuns(runs)


def get_evaluation_run(
    runs: SqlAlchemyEvaluationRunRepository = Depends(get_evaluation_run_repository),
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
) -> GetEvaluationRun:
    return GetEvaluationRun(runs, experiments)

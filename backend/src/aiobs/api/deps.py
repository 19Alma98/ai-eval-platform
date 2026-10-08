from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from aiobs.application.app_configs import (
    CreateAppConfig,
    DeleteAppConfigAlias,
    GetAppConfig,
    ListAppConfigAliases,
    ListAppConfigs,
    ListAppConfigVersions,
    SetAppConfigAlias,
)
from aiobs.application.compare import CompareExperiments, SummarizeExperiment
from aiobs.application.compare_items import CompareExperimentItems
from aiobs.application.datasets import (
    AddDatasetItem,
    AddDatasetItemFromTrace,
    CreateDataset,
    GetDataset,
    ImportDatasetItems,
    ListDatasets,
)
from aiobs.application.evaluate import (
    EvaluateExperiment,
    GetEvaluationRun,
    ListExperimentRuns,
    ScoreExperimentFromPack,
)
from aiobs.application.evaluators import CreateEvaluator, ListEvaluators
from aiobs.application.experiment_outputs import (
    ListExperimentOutputs,
    UpsertExperimentOutputs,
)
from aiobs.application.experiments import (
    CreateExperiment,
    GetExperiment,
    ListExperiments,
)
from aiobs.application.live_interactions import (
    GetLiveInteraction,
    ListLiveInteractions,
    PromoteLiveInteraction,
    ScoreLiveInteraction,
    SubmitLiveInteraction,
    UpsertLiveReview,
    UpsertLiveScoreReview,
)
from aiobs.application.live_judge_calibration import SummarizeLiveJudgeCalibration
from aiobs.application.metrics_packs import (
    EnsureMetricsPack,
    GetMetricsPack,
    ReplaceMetricsPack,
)
from aiobs.application.metrics_sets import (
    CreateMetricsSet,
    DeleteMetricsSet,
    DeleteMetricsSetEntry,
    EnsureProjectDefaultMetricsSet,
    GetMetricsSet,
    ListMetricsSets,
    PatchMetricsSet,
    ResolveMetricsSetForScore,
    VersionMetricsSet,
)
from aiobs.application.projects import (
    CreateProject,
    DeleteProject,
    GetProject,
    ListProjects,
)
from aiobs.application.release_check import ReleaseCheck
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
    SqlAlchemyAppConfigRepository,
    SqlAlchemyDatasetRepository,
    SqlAlchemyEvaluationRunRepository,
    SqlAlchemyEvaluatorRepository,
    SqlAlchemyExperimentItemOutputRepository,
    SqlAlchemyExperimentRepository,
    SqlAlchemyLiveInteractionRepository,
    SqlAlchemyMetricsSetRepository,
    SqlAlchemyProjectRepository,
    SqlAlchemyTraceRepository,
)
from aiobs.tracing.run_binding import BindOtlpTracesToExperimentOutputs


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


def get_app_config_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SqlAlchemyAppConfigRepository:
    return SqlAlchemyAppConfigRepository(session)


def get_dataset_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SqlAlchemyDatasetRepository:
    return SqlAlchemyDatasetRepository(session)


def get_evaluator_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SqlAlchemyEvaluatorRepository:
    return SqlAlchemyEvaluatorRepository(session)


def get_metrics_set_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SqlAlchemyMetricsSetRepository:
    return SqlAlchemyMetricsSetRepository(session)


def get_experiment_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SqlAlchemyExperimentRepository:
    return SqlAlchemyExperimentRepository(session)


def get_evaluation_run_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SqlAlchemyEvaluationRunRepository:
    return SqlAlchemyEvaluationRunRepository(session)


def get_experiment_item_output_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SqlAlchemyExperimentItemOutputRepository:
    return SqlAlchemyExperimentItemOutputRepository(session)


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


def get_delete_project(
    repository: SqlAlchemyProjectRepository = Depends(get_project_repository),
) -> DeleteProject:
    return DeleteProject(repository)


def get_ingest_traces(
    repository: SqlAlchemyTraceRepository = Depends(get_trace_repository),
) -> IngestNormalizedTraces:
    return IngestNormalizedTraces(repository)


def get_bind_otlp_traces(
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
    datasets: SqlAlchemyDatasetRepository = Depends(get_dataset_repository),
    outputs: SqlAlchemyExperimentItemOutputRepository = Depends(
        get_experiment_item_output_repository
    ),
) -> BindOtlpTracesToExperimentOutputs:
    return BindOtlpTracesToExperimentOutputs(experiments, datasets, outputs)


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


def get_create_app_config(
    app_configs: SqlAlchemyAppConfigRepository = Depends(get_app_config_repository),
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
) -> CreateAppConfig:
    return CreateAppConfig(app_configs, projects)


def get_list_app_configs(
    app_configs: SqlAlchemyAppConfigRepository = Depends(get_app_config_repository),
) -> ListAppConfigs:
    return ListAppConfigs(app_configs)


def get_get_app_config(
    app_configs: SqlAlchemyAppConfigRepository = Depends(get_app_config_repository),
) -> GetAppConfig:
    return GetAppConfig(app_configs)


def get_list_app_config_versions(
    app_configs: SqlAlchemyAppConfigRepository = Depends(get_app_config_repository),
) -> ListAppConfigVersions:
    return ListAppConfigVersions(app_configs)


def get_set_app_config_alias(
    app_configs: SqlAlchemyAppConfigRepository = Depends(get_app_config_repository),
) -> SetAppConfigAlias:
    return SetAppConfigAlias(app_configs)


def get_list_app_config_aliases(
    app_configs: SqlAlchemyAppConfigRepository = Depends(get_app_config_repository),
) -> ListAppConfigAliases:
    return ListAppConfigAliases(app_configs)


def get_delete_app_config_alias(
    app_configs: SqlAlchemyAppConfigRepository = Depends(get_app_config_repository),
) -> DeleteAppConfigAlias:
    return DeleteAppConfigAlias(app_configs)


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


def get_import_dataset_items(
    datasets: SqlAlchemyDatasetRepository = Depends(get_dataset_repository),
) -> ImportDatasetItems:
    return ImportDatasetItems(datasets)


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


def get_ensure_project_default_metrics_set(
    metrics_sets: SqlAlchemyMetricsSetRepository = Depends(get_metrics_set_repository),
    evaluators: SqlAlchemyEvaluatorRepository = Depends(get_evaluator_repository),
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
    create_evaluator: CreateEvaluator = Depends(get_create_evaluator),
) -> EnsureProjectDefaultMetricsSet:
    return EnsureProjectDefaultMetricsSet(metrics_sets, evaluators, projects, create_evaluator)


def get_patch_metrics_set(
    metrics_sets: SqlAlchemyMetricsSetRepository = Depends(get_metrics_set_repository),
    evaluators: SqlAlchemyEvaluatorRepository = Depends(get_evaluator_repository),
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
) -> PatchMetricsSet:
    return PatchMetricsSet(metrics_sets, evaluators, experiments)


def get_list_metrics_sets(
    metrics_sets: SqlAlchemyMetricsSetRepository = Depends(get_metrics_set_repository),
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
) -> ListMetricsSets:
    return ListMetricsSets(metrics_sets, projects)


def get_get_metrics_set(
    metrics_sets: SqlAlchemyMetricsSetRepository = Depends(get_metrics_set_repository),
) -> GetMetricsSet:
    return GetMetricsSet(metrics_sets)


def get_create_metrics_set(
    metrics_sets: SqlAlchemyMetricsSetRepository = Depends(get_metrics_set_repository),
    evaluators: SqlAlchemyEvaluatorRepository = Depends(get_evaluator_repository),
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
) -> CreateMetricsSet:
    return CreateMetricsSet(metrics_sets, evaluators, projects)


def get_version_metrics_set(
    metrics_sets: SqlAlchemyMetricsSetRepository = Depends(get_metrics_set_repository),
    evaluators: SqlAlchemyEvaluatorRepository = Depends(get_evaluator_repository),
) -> VersionMetricsSet:
    return VersionMetricsSet(metrics_sets, evaluators)


def get_delete_metrics_set(
    metrics_sets: SqlAlchemyMetricsSetRepository = Depends(get_metrics_set_repository),
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
) -> DeleteMetricsSet:
    return DeleteMetricsSet(metrics_sets, experiments)


def get_delete_metrics_set_entry(
    metrics_sets: SqlAlchemyMetricsSetRepository = Depends(get_metrics_set_repository),
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
) -> DeleteMetricsSetEntry:
    return DeleteMetricsSetEntry(metrics_sets, experiments)


def get_ensure_metrics_pack(
    ensure_default: EnsureProjectDefaultMetricsSet = Depends(
        get_ensure_project_default_metrics_set
    ),
) -> EnsureMetricsPack:
    return EnsureMetricsPack(ensure_default)


def get_get_metrics_pack(
    metrics_sets: SqlAlchemyMetricsSetRepository = Depends(get_metrics_set_repository),
) -> GetMetricsPack:
    return GetMetricsPack(metrics_sets)


def get_replace_metrics_pack(
    metrics_sets: SqlAlchemyMetricsSetRepository = Depends(get_metrics_set_repository),
    patch_metrics_set: PatchMetricsSet = Depends(get_patch_metrics_set),
) -> ReplaceMetricsPack:
    return ReplaceMetricsPack(metrics_sets, patch_metrics_set)


def get_create_dataset(
    datasets: SqlAlchemyDatasetRepository = Depends(get_dataset_repository),
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
    ensure_metrics_pack: EnsureMetricsPack = Depends(get_ensure_metrics_pack),
) -> CreateDataset:
    return CreateDataset(datasets, projects, ensure_metrics_pack)


def get_resolve_metrics_set_for_score(
    metrics_sets: SqlAlchemyMetricsSetRepository = Depends(get_metrics_set_repository),
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
    evaluators: SqlAlchemyEvaluatorRepository = Depends(get_evaluator_repository),
    create_evaluator: CreateEvaluator = Depends(get_create_evaluator),
    ensure_default: EnsureProjectDefaultMetricsSet = Depends(
        get_ensure_project_default_metrics_set
    ),
) -> ResolveMetricsSetForScore:
    return ResolveMetricsSetForScore(
        metrics_sets,
        experiments,
        evaluators,
        create_evaluator,
        ensure_default,
    )


def get_create_experiment(
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
    datasets: SqlAlchemyDatasetRepository = Depends(get_dataset_repository),
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
    app_configs: SqlAlchemyAppConfigRepository = Depends(get_app_config_repository),
    metrics_sets: SqlAlchemyMetricsSetRepository = Depends(get_metrics_set_repository),
) -> CreateExperiment:
    return CreateExperiment(experiments, datasets, projects, app_configs, metrics_sets)


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
    outputs: SqlAlchemyExperimentItemOutputRepository = Depends(
        get_experiment_item_output_repository
    ),
) -> EvaluateExperiment:
    return EvaluateExperiment(experiments, datasets, evaluators, runs, runner, outputs)


def get_score_experiment_from_pack(
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
    resolve_metrics_set: ResolveMetricsSetForScore = Depends(get_resolve_metrics_set_for_score),
    evaluate_experiment: EvaluateExperiment = Depends(get_evaluate_experiment),
) -> ScoreExperimentFromPack:
    return ScoreExperimentFromPack(
        experiments,
        resolve_metrics_set,
        evaluate_experiment,
    )


def get_list_experiment_runs(
    runs: SqlAlchemyEvaluationRunRepository = Depends(get_evaluation_run_repository),
) -> ListExperimentRuns:
    return ListExperimentRuns(runs)


def get_evaluation_run(
    runs: SqlAlchemyEvaluationRunRepository = Depends(get_evaluation_run_repository),
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
) -> GetEvaluationRun:
    return GetEvaluationRun(runs, experiments)


def get_summarize_experiment(
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
    runs: SqlAlchemyEvaluationRunRepository = Depends(get_evaluation_run_repository),
    evaluators: SqlAlchemyEvaluatorRepository = Depends(get_evaluator_repository),
) -> SummarizeExperiment:
    return SummarizeExperiment(experiments, runs, evaluators)


def get_compare_experiments(
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
    runs: SqlAlchemyEvaluationRunRepository = Depends(get_evaluation_run_repository),
    evaluators: SqlAlchemyEvaluatorRepository = Depends(get_evaluator_repository),
) -> CompareExperiments:
    return CompareExperiments(experiments, runs, evaluators)


def get_compare_experiment_items(
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
    datasets: SqlAlchemyDatasetRepository = Depends(get_dataset_repository),
    runs: SqlAlchemyEvaluationRunRepository = Depends(get_evaluation_run_repository),
    outputs: SqlAlchemyExperimentItemOutputRepository = Depends(
        get_experiment_item_output_repository
    ),
) -> CompareExperimentItems:
    return CompareExperimentItems(experiments, datasets, runs, outputs)


def get_upsert_experiment_outputs(
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
    datasets: SqlAlchemyDatasetRepository = Depends(get_dataset_repository),
    outputs: SqlAlchemyExperimentItemOutputRepository = Depends(
        get_experiment_item_output_repository
    ),
) -> UpsertExperimentOutputs:
    return UpsertExperimentOutputs(experiments, datasets, outputs)


def get_list_experiment_outputs(
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
    outputs: SqlAlchemyExperimentItemOutputRepository = Depends(
        get_experiment_item_output_repository
    ),
) -> ListExperimentOutputs:
    return ListExperimentOutputs(experiments, outputs)


def get_release_check(
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
    runs: SqlAlchemyEvaluationRunRepository = Depends(get_evaluation_run_repository),
    compare: CompareExperiments = Depends(get_compare_experiments),
) -> ReleaseCheck:
    return ReleaseCheck(projects, experiments, runs, compare)


def get_live_interaction_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SqlAlchemyLiveInteractionRepository:
    return SqlAlchemyLiveInteractionRepository(session)


def get_submit_live_interaction(
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
    live: SqlAlchemyLiveInteractionRepository = Depends(get_live_interaction_repository),
    metrics_sets: SqlAlchemyMetricsSetRepository = Depends(get_metrics_set_repository),
) -> SubmitLiveInteraction:
    return SubmitLiveInteraction(projects, live, metrics_sets)


def get_score_live_interaction(
    live: SqlAlchemyLiveInteractionRepository = Depends(get_live_interaction_repository),
    metrics_sets: SqlAlchemyMetricsSetRepository = Depends(get_metrics_set_repository),
    evaluators: SqlAlchemyEvaluatorRepository = Depends(get_evaluator_repository),
    create_evaluator: CreateEvaluator = Depends(get_create_evaluator),
    ensure_default: EnsureProjectDefaultMetricsSet = Depends(
        get_ensure_project_default_metrics_set
    ),
) -> ScoreLiveInteraction:
    return ScoreLiveInteraction(live, metrics_sets, evaluators, create_evaluator, ensure_default)


def get_list_live_interactions(
    live: SqlAlchemyLiveInteractionRepository = Depends(get_live_interaction_repository),
) -> ListLiveInteractions:
    return ListLiveInteractions(live)


def get_get_live_interaction(
    live: SqlAlchemyLiveInteractionRepository = Depends(get_live_interaction_repository),
) -> GetLiveInteraction:
    return GetLiveInteraction(live)


def get_upsert_live_review(
    live: SqlAlchemyLiveInteractionRepository = Depends(get_live_interaction_repository),
) -> UpsertLiveReview:
    return UpsertLiveReview(live)


def get_upsert_live_score_review(
    live: SqlAlchemyLiveInteractionRepository = Depends(get_live_interaction_repository),
) -> UpsertLiveScoreReview:
    return UpsertLiveScoreReview(live)


def get_summarize_live_judge_calibration(
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
    live: SqlAlchemyLiveInteractionRepository = Depends(get_live_interaction_repository),
) -> SummarizeLiveJudgeCalibration:
    return SummarizeLiveJudgeCalibration(projects, live)


def get_promote_live_interaction(
    live: SqlAlchemyLiveInteractionRepository = Depends(get_live_interaction_repository),
    datasets: SqlAlchemyDatasetRepository = Depends(get_dataset_repository),
    add_item: AddDatasetItem = Depends(get_add_dataset_item),
) -> PromoteLiveInteraction:
    return PromoteLiveInteraction(live, datasets, add_item)

from collections.abc import AsyncGenerator, Awaitable, Callable

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from opengrade_server.application.alerts import (
    AlertDispatcher,
    AlertNotifier,
    EvaluateAlertRules,
    ManageAlertRules,
)
from opengrade_server.application.app_configs import (
    CreateAppConfig,
    DeleteAppConfigAlias,
    GetAppConfig,
    ListAppConfigAliases,
    ListAppConfigs,
    ListAppConfigVersions,
    SetAppConfigAlias,
)
from opengrade_server.application.client_results import SubmitClientResults
from opengrade_server.application.compare import (
    CompareExperiments,
    SummarizeExperiment,
    SummarizeExperiments,
)
from opengrade_server.application.compare_items import CompareExperimentItems
from opengrade_server.application.datasets import (
    AddDatasetItem,
    CreateDataset,
    DeleteDataset,
    GetDataset,
    ImportDatasetItems,
    ListDatasets,
)
from opengrade_server.application.evaluate import (
    EvaluateExperiment,
    EvaluateExperimentCommand,
    GetEvaluationRun,
    ListExperimentRuns,
    ScoreExperimentFromPack,
    StartEvaluateExperiment,
)
from opengrade_server.application.evaluators import CreateEvaluator, ListEvaluators
from opengrade_server.application.experiment_aliases import (
    DeleteExperimentAlias,
    GetExperimentAlias,
    ListExperimentAliases,
    ListExperimentAliasHistory,
    SetExperimentAlias,
)
from opengrade_server.application.experiment_metrics import (
    GetExperimentMetrics,
    LogExperimentMetrics,
    UpdateExperimentParams,
)
from opengrade_server.application.experiment_outputs import (
    ListExperimentOutputs,
    UpsertExperimentOutputs,
)
from opengrade_server.application.experiments import (
    CreateExperiment,
    GetExperiment,
    ListExperiments,
)
from opengrade_server.application.live_interactions import (
    GetLiveInteraction,
    ListLiveInteractions,
    PromoteLiveInteraction,
    ScoreLiveInteraction,
    SubmitLiveInteraction,
    UpsertLiveScoreReview,
)
from opengrade_server.application.live_judge_calibration import SummarizeLiveJudgeCalibration
from opengrade_server.application.metrics_packs import (
    EnsureMetricsPack,
    GetMetricsPack,
    ReplaceMetricsPack,
)
from opengrade_server.application.metrics_sets import (
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
from opengrade_server.application.monitoring import (
    GetProductionMonitoring,
    GetProductionVersions,
    GetReleaseFacets,
)
from opengrade_server.application.project_overview import GetProjectOverview
from opengrade_server.application.projects import (
    CreateProject,
    DeleteProject,
    GetProject,
    ListProjects,
)
from opengrade_server.application.release_check import ReleaseCheck
from opengrade_server.application.scoring_inputs import CurrentScoringFingerprint
from opengrade_server.application.trace_scores import (
    ListTraceScores,
    LogTraceScores,
    SummarizeTraceScores,
)
from opengrade_server.application.traces import (
    GetTrace,
    IngestNormalizedTraces,
    ListTraces,
    ResolveProject,
    ResolveTraceLiveLinks,
)
from opengrade_server.config import Settings, get_settings
from opengrade_server.evaluation.runner import EvaluationRunner
from opengrade_server.infrastructure.db import get_session
from opengrade_server.infrastructure.repositories import (
    SqlAlchemyAlertRepository,
    SqlAlchemyAppConfigRepository,
    SqlAlchemyDatasetRepository,
    SqlAlchemyEvaluationRunRepository,
    SqlAlchemyEvaluatorRepository,
    SqlAlchemyExperimentAliasRepository,
    SqlAlchemyExperimentItemOutputRepository,
    SqlAlchemyExperimentMetricRepository,
    SqlAlchemyExperimentRepository,
    SqlAlchemyLiveInteractionRepository,
    SqlAlchemyMetricsSetRepository,
    SqlAlchemyProjectRepository,
    SqlAlchemyTraceRepository,
    SqlAlchemyTraceScoreRepository,
)
from opengrade_server.infrastructure.webhooks import HttpWebhookNotifier
from opengrade_server.tracing.live_binding import CreateLiveInteractionsFromTraces
from opengrade_server.tracing.run_binding import BindOtlpTracesToExperimentOutputs


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


def get_experiment_alias_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SqlAlchemyExperimentAliasRepository:
    return SqlAlchemyExperimentAliasRepository(session)


def get_evaluation_run_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SqlAlchemyEvaluationRunRepository:
    return SqlAlchemyEvaluationRunRepository(session)


def get_experiment_item_output_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SqlAlchemyExperimentItemOutputRepository:
    return SqlAlchemyExperimentItemOutputRepository(session)


def get_experiment_metric_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SqlAlchemyExperimentMetricRepository:
    return SqlAlchemyExperimentMetricRepository(session)


def get_trace_score_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SqlAlchemyTraceScoreRepository:
    return SqlAlchemyTraceScoreRepository(session)


def get_log_trace_scores(
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
    scores: SqlAlchemyTraceScoreRepository = Depends(get_trace_score_repository),
) -> LogTraceScores:
    return LogTraceScores(projects, scores)


def get_list_trace_scores(
    scores: SqlAlchemyTraceScoreRepository = Depends(get_trace_score_repository),
) -> ListTraceScores:
    return ListTraceScores(scores)


def get_summarize_trace_scores(
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
    scores: SqlAlchemyTraceScoreRepository = Depends(get_trace_score_repository),
) -> SummarizeTraceScores:
    return SummarizeTraceScores(projects, scores)


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
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
) -> ListAppConfigs:
    return ListAppConfigs(app_configs, projects)


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
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
) -> ListDatasets:
    return ListDatasets(datasets, projects)


def get_get_dataset(
    datasets: SqlAlchemyDatasetRepository = Depends(get_dataset_repository),
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
    runs: SqlAlchemyEvaluationRunRepository = Depends(get_evaluation_run_repository),
) -> GetDataset:
    return GetDataset(datasets, experiments, runs)


def get_add_dataset_item(
    datasets: SqlAlchemyDatasetRepository = Depends(get_dataset_repository),
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
    runs: SqlAlchemyEvaluationRunRepository = Depends(get_evaluation_run_repository),
) -> AddDatasetItem:
    return AddDatasetItem(datasets, experiments, runs)


def get_import_dataset_items(
    datasets: SqlAlchemyDatasetRepository = Depends(get_dataset_repository),
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
    runs: SqlAlchemyEvaluationRunRepository = Depends(get_evaluation_run_repository),
) -> ImportDatasetItems:
    return ImportDatasetItems(datasets, experiments, runs)


def get_delete_dataset(
    datasets: SqlAlchemyDatasetRepository = Depends(get_dataset_repository),
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
) -> DeleteDataset:
    return DeleteDataset(datasets, experiments)


def get_create_evaluator(
    evaluators: SqlAlchemyEvaluatorRepository = Depends(get_evaluator_repository),
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
) -> CreateEvaluator:
    return CreateEvaluator(evaluators, projects)


def get_list_evaluators(
    evaluators: SqlAlchemyEvaluatorRepository = Depends(get_evaluator_repository),
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
) -> ListEvaluators:
    return ListEvaluators(evaluators, projects)


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
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
) -> ListExperiments:
    return ListExperiments(experiments, projects)


def get_get_experiment(
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
) -> GetExperiment:
    return GetExperiment(experiments)


def get_set_experiment_alias(
    aliases: SqlAlchemyExperimentAliasRepository = Depends(get_experiment_alias_repository),
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
) -> SetExperimentAlias:
    return SetExperimentAlias(aliases, experiments, projects)


def get_get_experiment_alias(
    aliases: SqlAlchemyExperimentAliasRepository = Depends(get_experiment_alias_repository),
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
) -> GetExperimentAlias:
    return GetExperimentAlias(aliases, experiments, projects)


def get_list_experiment_aliases(
    aliases: SqlAlchemyExperimentAliasRepository = Depends(get_experiment_alias_repository),
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
) -> ListExperimentAliases:
    return ListExperimentAliases(aliases, experiments, projects)


def get_list_experiment_alias_history(
    aliases: SqlAlchemyExperimentAliasRepository = Depends(get_experiment_alias_repository),
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
) -> ListExperimentAliasHistory:
    return ListExperimentAliasHistory(aliases, projects)


def get_delete_experiment_alias(
    aliases: SqlAlchemyExperimentAliasRepository = Depends(get_experiment_alias_repository),
) -> DeleteExperimentAlias:
    return DeleteExperimentAlias(aliases)


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


def get_start_evaluate_experiment(
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
    evaluators: SqlAlchemyEvaluatorRepository = Depends(get_evaluator_repository),
) -> StartEvaluateExperiment:
    return StartEvaluateExperiment(experiments, evaluators)


EvaluateBackgroundRunner = Callable[[EvaluateExperimentCommand], Awaitable[None]]


def get_evaluate_background_runner(
    evaluate_experiment: EvaluateExperiment = Depends(get_evaluate_experiment),
) -> EvaluateBackgroundRunner:
    """Run scoring in BackgroundTasks with the request-scoped use case.

    FastAPI keeps yield-dependencies open until background tasks finish, so the
    request session (or in-memory test repos) remains valid. Use
    :func:`schedule_evaluate_experiment` only from non-request callers.
    """

    async def _run(command: EvaluateExperimentCommand) -> None:
        try:
            await evaluate_experiment.execute(command)
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "Background experiment score failed: %s", command.experiment_id
            )

    return _run


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


def get_current_scoring_fingerprint(
    datasets: SqlAlchemyDatasetRepository = Depends(get_dataset_repository),
    outputs: SqlAlchemyExperimentItemOutputRepository = Depends(
        get_experiment_item_output_repository
    ),
) -> CurrentScoringFingerprint:
    return CurrentScoringFingerprint(datasets, outputs)


def get_summarize_experiment(
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
    runs: SqlAlchemyEvaluationRunRepository = Depends(get_evaluation_run_repository),
    evaluators: SqlAlchemyEvaluatorRepository = Depends(get_evaluator_repository),
    fingerprints: CurrentScoringFingerprint = Depends(get_current_scoring_fingerprint),
    metrics: SqlAlchemyExperimentMetricRepository = Depends(get_experiment_metric_repository),
    datasets: SqlAlchemyDatasetRepository = Depends(get_dataset_repository),
) -> SummarizeExperiment:
    return SummarizeExperiment(experiments, runs, evaluators, fingerprints, metrics, datasets)


def get_compare_experiments(
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
    runs: SqlAlchemyEvaluationRunRepository = Depends(get_evaluation_run_repository),
    evaluators: SqlAlchemyEvaluatorRepository = Depends(get_evaluator_repository),
    fingerprints: CurrentScoringFingerprint = Depends(get_current_scoring_fingerprint),
    metrics: SqlAlchemyExperimentMetricRepository = Depends(get_experiment_metric_repository),
    datasets: SqlAlchemyDatasetRepository = Depends(get_dataset_repository),
) -> CompareExperiments:
    return CompareExperiments(experiments, runs, evaluators, fingerprints, metrics, datasets)


def get_compare_experiment_items(
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
    datasets: SqlAlchemyDatasetRepository = Depends(get_dataset_repository),
    runs: SqlAlchemyEvaluationRunRepository = Depends(get_evaluation_run_repository),
    outputs: SqlAlchemyExperimentItemOutputRepository = Depends(
        get_experiment_item_output_repository
    ),
    fingerprints: CurrentScoringFingerprint = Depends(get_current_scoring_fingerprint),
) -> CompareExperimentItems:
    return CompareExperimentItems(experiments, datasets, runs, outputs, fingerprints)


def get_submit_client_results(
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
    datasets: SqlAlchemyDatasetRepository = Depends(get_dataset_repository),
    outputs: SqlAlchemyExperimentItemOutputRepository = Depends(
        get_experiment_item_output_repository
    ),
    evaluators: SqlAlchemyEvaluatorRepository = Depends(get_evaluator_repository),
    runs: SqlAlchemyEvaluationRunRepository = Depends(get_evaluation_run_repository),
) -> SubmitClientResults:
    return SubmitClientResults(experiments, datasets, outputs, evaluators, runs)


def get_log_experiment_metrics(
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
    metrics: SqlAlchemyExperimentMetricRepository = Depends(get_experiment_metric_repository),
) -> LogExperimentMetrics:
    return LogExperimentMetrics(experiments, metrics)


def get_get_experiment_metrics(
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
    metrics: SqlAlchemyExperimentMetricRepository = Depends(get_experiment_metric_repository),
) -> GetExperimentMetrics:
    return GetExperimentMetrics(experiments, metrics)


def get_update_experiment_params(
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
    runs: SqlAlchemyEvaluationRunRepository = Depends(get_evaluation_run_repository),
) -> UpdateExperimentParams:
    return UpdateExperimentParams(experiments, runs)


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
    fingerprints: CurrentScoringFingerprint = Depends(get_current_scoring_fingerprint),
    metrics: SqlAlchemyExperimentMetricRepository = Depends(get_experiment_metric_repository),
    datasets: SqlAlchemyDatasetRepository = Depends(get_dataset_repository),
) -> ReleaseCheck:
    return ReleaseCheck(projects, experiments, runs, compare, fingerprints, metrics, datasets)


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


def get_create_live_from_traces(
    submit: SubmitLiveInteraction = Depends(get_submit_live_interaction),
) -> CreateLiveInteractionsFromTraces:
    return CreateLiveInteractionsFromTraces(submit)


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
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
    trace_scores: SqlAlchemyTraceScoreRepository = Depends(get_trace_score_repository),
) -> ListLiveInteractions:
    return ListLiveInteractions(live, projects, trace_scores)


def get_get_live_interaction(
    live: SqlAlchemyLiveInteractionRepository = Depends(get_live_interaction_repository),
    trace_scores: SqlAlchemyTraceScoreRepository = Depends(get_trace_score_repository),
) -> GetLiveInteraction:
    return GetLiveInteraction(live, trace_scores)


def get_upsert_live_score_review(
    live: SqlAlchemyLiveInteractionRepository = Depends(get_live_interaction_repository),
) -> UpsertLiveScoreReview:
    return UpsertLiveScoreReview(live)


def get_summarize_live_judge_calibration(
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
    live: SqlAlchemyLiveInteractionRepository = Depends(get_live_interaction_repository),
) -> SummarizeLiveJudgeCalibration:
    return SummarizeLiveJudgeCalibration(projects, live)


def get_project_overview(
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
    datasets: SqlAlchemyDatasetRepository = Depends(get_dataset_repository),
    metrics_sets: SqlAlchemyMetricsSetRepository = Depends(get_metrics_set_repository),
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
    live: SqlAlchemyLiveInteractionRepository = Depends(get_live_interaction_repository),
    compare: CompareExperiments = Depends(get_compare_experiments),
    calibration: SummarizeLiveJudgeCalibration = Depends(get_summarize_live_judge_calibration),
    trace_scores: SqlAlchemyTraceScoreRepository = Depends(get_trace_score_repository),
) -> GetProjectOverview:
    return GetProjectOverview(
        projects,
        datasets,
        metrics_sets,
        experiments,
        live,
        compare,
        calibration,
        trace_scores,
    )


def get_promote_live_interaction(
    live: SqlAlchemyLiveInteractionRepository = Depends(get_live_interaction_repository),
    datasets: SqlAlchemyDatasetRepository = Depends(get_dataset_repository),
    add_item: AddDatasetItem = Depends(get_add_dataset_item),
) -> PromoteLiveInteraction:
    return PromoteLiveInteraction(live, datasets, add_item)


def get_resolve_trace_live_links(
    live: SqlAlchemyLiveInteractionRepository = Depends(get_live_interaction_repository),
) -> ResolveTraceLiveLinks:
    return ResolveTraceLiveLinks(live)


def get_list_traces(
    repository: SqlAlchemyTraceRepository = Depends(get_trace_repository),
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
    trace_scores: SqlAlchemyTraceScoreRepository = Depends(get_trace_score_repository),
    live_links: ResolveTraceLiveLinks = Depends(get_resolve_trace_live_links),
) -> ListTraces:
    return ListTraces(repository, projects, trace_scores, live_links)


def get_production_monitoring(
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
    traces: SqlAlchemyTraceRepository = Depends(get_trace_repository),
    live: SqlAlchemyLiveInteractionRepository = Depends(get_live_interaction_repository),
    trace_scores: SqlAlchemyTraceScoreRepository = Depends(get_trace_score_repository),
) -> GetProductionMonitoring:
    return GetProductionMonitoring(projects, traces, live, trace_scores)


def get_production_versions(
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
    traces: SqlAlchemyTraceRepository = Depends(get_trace_repository),
    monitoring: GetProductionMonitoring = Depends(get_production_monitoring),
) -> GetProductionVersions:
    return GetProductionVersions(projects, traces, monitoring)


def get_release_facets(
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
    traces: SqlAlchemyTraceRepository = Depends(get_trace_repository),
) -> GetReleaseFacets:
    return GetReleaseFacets(projects, traces)


def get_summarize_experiments(
    experiments: SqlAlchemyExperimentRepository = Depends(get_experiment_repository),
    summarize: SummarizeExperiment = Depends(get_summarize_experiment),
) -> SummarizeExperiments:
    return SummarizeExperiments(experiments, summarize)


def get_alert_repository(
    session: AsyncSession = Depends(get_db_session),
) -> SqlAlchemyAlertRepository:
    return SqlAlchemyAlertRepository(session)


def get_alert_notifier() -> AlertNotifier:
    return HttpWebhookNotifier()


def get_alert_dispatcher(
    alerts: SqlAlchemyAlertRepository = Depends(get_alert_repository),
    notifier: AlertNotifier = Depends(get_alert_notifier),
) -> AlertDispatcher:
    settings = get_settings()
    return AlertDispatcher(
        alerts,
        notifier,
        default_webhook_url=settings.alert_webhook_url,
        public_base_url=settings.public_base_url,
    )


def get_manage_alert_rules(
    alerts: SqlAlchemyAlertRepository = Depends(get_alert_repository),
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
    dispatcher: AlertDispatcher = Depends(get_alert_dispatcher),
) -> ManageAlertRules:
    return ManageAlertRules(alerts, projects, dispatcher)


def get_evaluate_alert_rules(
    alerts: SqlAlchemyAlertRepository = Depends(get_alert_repository),
    projects: SqlAlchemyProjectRepository = Depends(get_project_repository),
    monitoring: GetProductionMonitoring = Depends(get_production_monitoring),
    dispatcher: AlertDispatcher = Depends(get_alert_dispatcher),
) -> EvaluateAlertRules:
    return EvaluateAlertRules(alerts, projects, monitoring, dispatcher)

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from aiobs.domain.app_config import AppConfig, AppConfigAlias
from aiobs.domain.dataset import Dataset, DatasetItem
from aiobs.domain.evaluation import EvaluationResultRecord, EvaluationRun
from aiobs.domain.evaluator import Evaluator
from aiobs.domain.experiment import Experiment
from aiobs.domain.experiment_output import ExperimentItemOutput
from aiobs.domain.live_interaction import (
    DuplicateExternalIdError,
    LiveInteraction,
    LiveInteractionScore,
    LiveReview,
)
from aiobs.domain.metrics_set import MetricsSet, MetricsSetEntry
from aiobs.domain.project import Project
from aiobs.domain.trace import Span, Trace
from aiobs.infrastructure.models import (
    AppConfigAliasModel,
    AppConfigModel,
    DatasetItemModel,
    DatasetModel,
    EvaluationResultModel,
    EvaluationRunModel,
    EvaluatorModel,
    ExperimentItemOutputModel,
    ExperimentModel,
    LiveInteractionModel,
    LiveInteractionScoreModel,
    LiveReviewModel,
    MetricsSetEntryModel,
    MetricsSetModel,
    ProjectModel,
    SpanModel,
    TraceModel,
)


def escape_like(value: str) -> str:
    """Escape LIKE/ILIKE wildcards so user input matches literally (escape char: backslash)."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _project_to_domain(row: ProjectModel) -> Project:
    return Project(
        id=row.id,
        name=row.name,
        slug=row.slug,
        created_at=row.created_at,
    )


def _span_to_domain(row: SpanModel) -> Span:
    return Span(
        id=row.id,
        span_id=row.span_id,
        parent_span_id=row.parent_span_id,
        name=row.name,
        kind=row.kind,
        start_time=row.start_time,
        end_time=row.end_time,
        status=row.status,
        attributes=dict(row.attributes or {}),
        events=list(row.events or []),
    )


def _trace_to_domain(row: TraceModel, *, include_spans: bool = True) -> Trace:
    spans = tuple(_span_to_domain(s) for s in row.spans) if include_spans else ()
    return Trace(
        id=row.id,
        project_id=row.project_id,
        trace_id=row.trace_id,
        name=row.name,
        status=row.status,
        start_time=row.start_time,
        end_time=row.end_time,
        input=row.input,
        output=row.output,
        metadata=dict(row.metadata_json or {}),
        environment=row.environment,
        user_id=row.user_id,
        session_id=row.session_id,
        spans=spans,
    )


class SqlAlchemyProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, project: Project) -> Project:
        row = ProjectModel(
            id=project.id,
            name=project.name,
            slug=project.slug,
            created_at=project.created_at,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return _project_to_domain(row)

    async def get_by_id(self, project_id: uuid.UUID) -> Project | None:
        row = await self._session.get(ProjectModel, project_id)
        return _project_to_domain(row) if row is not None else None

    async def get_by_slug(self, slug: str) -> Project | None:
        result = await self._session.execute(select(ProjectModel).where(ProjectModel.slug == slug))
        row = result.scalar_one_or_none()
        return _project_to_domain(row) if row is not None else None

    async def list_all(self) -> list[Project]:
        result = await self._session.execute(
            select(ProjectModel).order_by(ProjectModel.created_at.desc())
        )
        return [_project_to_domain(row) for row in result.scalars().all()]

    async def delete(self, project_id: uuid.UUID) -> bool:
        row = await self._session.get(ProjectModel, project_id)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.commit()
        return True


class SqlAlchemyTraceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, trace: Trace) -> Trace:
        result = await self._session.execute(
            select(TraceModel)
            .options(selectinload(TraceModel.spans))
            .where(
                TraceModel.project_id == trace.project_id,
                TraceModel.trace_id == trace.trace_id,
            )
        )
        existing = result.scalar_one_or_none()

        if existing is not None:
            existing.name = trace.name or existing.name
            # Prefer error if either side reported it.
            if trace.status == "error" or existing.status == "error":
                existing.status = "error"
            elif trace.status == "ok" or existing.status == "ok":
                existing.status = "ok"
            else:
                existing.status = trace.status or existing.status
            if trace.start_time and (
                existing.start_time is None or trace.start_time < existing.start_time
            ):
                existing.start_time = trace.start_time
            if trace.end_time and (existing.end_time is None or trace.end_time > existing.end_time):
                existing.end_time = trace.end_time
            if trace.input is not None:
                existing.input = trace.input
            if trace.output is not None:
                existing.output = trace.output
            merged_meta = dict(existing.metadata_json or {})
            merged_meta.update(dict(trace.metadata))
            existing.metadata_json = merged_meta
            if trace.environment is not None:
                existing.environment = trace.environment
            if trace.user_id is not None:
                existing.user_id = trace.user_id
            if trace.session_id is not None:
                existing.session_id = trace.session_id

            by_span_id = {span.span_id: span for span in existing.spans}
            for span in trace.spans:
                current = by_span_id.get(span.span_id)
                if current is None:
                    self._session.add(
                        SpanModel(
                            id=span.id,
                            trace_pk=existing.id,
                            project_id=trace.project_id,
                            span_id=span.span_id,
                            parent_span_id=span.parent_span_id,
                            name=span.name,
                            kind=span.kind,
                            start_time=span.start_time,
                            end_time=span.end_time,
                            status=span.status,
                            attributes=dict(span.attributes),
                            events=list(span.events),
                        )
                    )
                else:
                    current.parent_span_id = span.parent_span_id
                    current.name = span.name
                    current.kind = span.kind
                    current.start_time = span.start_time
                    current.end_time = span.end_time
                    current.status = span.status
                    current.attributes = dict(span.attributes)
                    current.events = list(span.events)

            await self._session.commit()
            refreshed = await self.get_by_trace_id(trace.project_id, trace.trace_id)
            assert refreshed is not None
            return refreshed

        row = TraceModel(
            id=trace.id,
            project_id=trace.project_id,
            trace_id=trace.trace_id,
            name=trace.name,
            status=trace.status,
            start_time=trace.start_time,
            end_time=trace.end_time,
            input=trace.input,
            output=trace.output,
            metadata_json=dict(trace.metadata),
            environment=trace.environment,
            user_id=trace.user_id,
            session_id=trace.session_id,
        )
        self._session.add(row)
        for span in trace.spans:
            self._session.add(
                SpanModel(
                    id=span.id,
                    trace_pk=trace.id,
                    project_id=trace.project_id,
                    span_id=span.span_id,
                    parent_span_id=span.parent_span_id,
                    name=span.name,
                    kind=span.kind,
                    start_time=span.start_time,
                    end_time=span.end_time,
                    status=span.status,
                    attributes=dict(span.attributes),
                    events=list(span.events),
                )
            )

        await self._session.commit()
        # Span rows were added separately; expire so selectinload is not stuck
        # on the empty in-memory collection of this new TraceModel.
        self._session.expire(row, ["spans"])
        refreshed = await self.get_by_trace_id(trace.project_id, trace.trace_id)
        assert refreshed is not None
        return refreshed

    async def get_by_trace_id(self, project_id: uuid.UUID, trace_id: str) -> Trace | None:
        result = await self._session.execute(
            select(TraceModel)
            .options(selectinload(TraceModel.spans))
            .where(
                TraceModel.project_id == project_id,
                TraceModel.trace_id == trace_id,
            )
        )
        row = result.scalar_one_or_none()
        return _trace_to_domain(row) if row is not None else None

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        cursor_start_time: datetime | None = None,
        cursor_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[Trace]:
        stmt = select(TraceModel).where(TraceModel.project_id == project_id)
        if status is not None:
            stmt = stmt.where(TraceModel.status == status)
        if start_time is not None:
            stmt = stmt.where(TraceModel.start_time >= start_time)
        if end_time is not None:
            stmt = stmt.where(TraceModel.start_time <= end_time)
        if cursor_start_time is not None and cursor_id is not None:
            stmt = stmt.where(
                (TraceModel.start_time < cursor_start_time)
                | ((TraceModel.start_time == cursor_start_time) & (TraceModel.id < cursor_id))
            )
        stmt = stmt.order_by(TraceModel.start_time.desc(), TraceModel.id.desc()).limit(limit)
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        traces = [_trace_to_domain(row, include_spans=False) for row in rows]
        if not traces:
            return traces

        ids = [t.id for t in traces]
        count_result = await self._session.execute(
            select(SpanModel.trace_pk, func.count(SpanModel.id))
            .where(SpanModel.trace_pk.in_(ids))
            .group_by(SpanModel.trace_pk)
        )
        counts = {trace_pk: count for trace_pk, count in count_result.all()}
        # Attach counts via temporary metadata key consumed by ListTraces
        return [
            Trace(
                id=t.id,
                project_id=t.project_id,
                trace_id=t.trace_id,
                name=t.name,
                status=t.status,
                start_time=t.start_time,
                end_time=t.end_time,
                input=t.input,
                output=t.output,
                metadata={**t.metadata, "_span_count": counts.get(t.id, 0)},
                environment=t.environment,
                user_id=t.user_id,
                session_id=t.session_id,
                spans=(),
            )
            for t in traces
        ]


def _dataset_to_domain(row: DatasetModel) -> Dataset:
    return Dataset(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        version=row.version,
        description=row.description,
        task_type=row.task_type,
        created_at=row.created_at,
    )


def _item_to_domain(row: DatasetItemModel) -> DatasetItem:
    return DatasetItem(
        id=row.id,
        dataset_id=row.dataset_id,
        input=row.input,
        expected_output=row.expected_output,
        actual_output=row.actual_output,
        context=row.context,
        metadata=dict(row.metadata_json or {}),
        source_trace_id=row.source_trace_id,
        source_span_id=row.source_span_id,
    )


def _evaluator_to_domain(row: EvaluatorModel) -> Evaluator:
    return Evaluator(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        type=row.type,
        config=dict(row.config or {}),
        version=row.version,
    )


def _app_config_to_domain(row: AppConfigModel) -> AppConfig:
    return AppConfig(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        version=row.version,
        description=row.description,
        prompt=dict(row.prompt or {}),
        model=dict(row.model or {}),
        retrieval=dict(row.retrieval or {}),
        content_hash=row.content_hash,
        created_at=row.created_at,
    )


def _app_config_alias_to_domain(row: AppConfigAliasModel) -> AppConfigAlias:
    return AppConfigAlias(
        project_id=row.project_id,
        name=row.name,
        app_config_id=row.app_config_id,
        updated_at=row.updated_at,
    )


def _experiment_to_domain(row: ExperimentModel) -> Experiment:
    return Experiment(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        dataset_id=row.dataset_id,
        model_config=dict(row.model_config_json or {}),
        version=row.version,
        baseline_experiment_id=row.baseline_experiment_id,
        status=row.status,
        created_at=row.created_at,
        app_config_id=row.app_config_id,
        metrics_set_id=row.metrics_set_id,
    )


def _run_to_domain(row: EvaluationRunModel) -> EvaluationRun:
    return EvaluationRun(
        id=row.id,
        experiment_id=row.experiment_id,
        evaluator_id=row.evaluator_id,
        status=row.status,
        started_at=row.started_at,
        finished_at=row.finished_at,
        metadata=dict(row.metadata_json or {}),
    )


def _result_to_domain(row: EvaluationResultModel) -> EvaluationResultRecord:
    return EvaluationResultRecord(
        id=row.id,
        run_id=row.run_id,
        dataset_item_id=row.dataset_item_id,
        score=row.score,
        label=row.label,
        explanation=row.explanation,
        metadata=dict(row.metadata_json or {}),
        duration_ms=row.duration_ms,
    )


def _experiment_item_output_to_domain(row: ExperimentItemOutputModel) -> ExperimentItemOutput:
    return ExperimentItemOutput(
        id=row.id,
        experiment_id=row.experiment_id,
        dataset_item_id=row.dataset_item_id,
        actual_output=row.actual_output,
        context=row.context,
        metadata=dict(row.metadata_json or {}),
        updated_at=row.updated_at,
    )


def _experiment_item_output_to_model(output: ExperimentItemOutput) -> ExperimentItemOutputModel:
    return ExperimentItemOutputModel(
        id=output.id,
        experiment_id=output.experiment_id,
        dataset_item_id=output.dataset_item_id,
        actual_output=output.actual_output,
        context=output.context,
        metadata_json=dict(output.metadata),
        updated_at=output.updated_at,
    )


class SqlAlchemyDatasetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, dataset: Dataset) -> Dataset:
        row = DatasetModel(
            id=dataset.id,
            project_id=dataset.project_id,
            name=dataset.name,
            version=dataset.version,
            description=dataset.description,
            task_type=dataset.task_type,
            created_at=dataset.created_at,
        )
        self._session.add(row)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            raise
        await self._session.refresh(row)
        return _dataset_to_domain(row)

    async def get_by_id(self, dataset_id: uuid.UUID) -> Dataset | None:
        row = await self._session.get(DatasetModel, dataset_id)
        return _dataset_to_domain(row) if row is not None else None

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        *,
        task_type: str | None = None,
    ) -> list[Dataset]:
        stmt = select(DatasetModel).where(DatasetModel.project_id == project_id)
        if task_type is not None:
            stmt = stmt.where(DatasetModel.task_type == task_type)
        result = await self._session.execute(stmt.order_by(DatasetModel.created_at.desc()))
        return [_dataset_to_domain(row) for row in result.scalars().all()]

    async def add_item(self, item: DatasetItem) -> DatasetItem:
        row = DatasetItemModel(
            id=item.id,
            dataset_id=item.dataset_id,
            input=item.input,
            expected_output=item.expected_output,
            actual_output=item.actual_output,
            context=item.context,
            metadata_json=dict(item.metadata),
            source_trace_id=item.source_trace_id,
            source_span_id=item.source_span_id,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return _item_to_domain(row)

    async def list_items(self, dataset_id: uuid.UUID) -> list[DatasetItem]:
        result = await self._session.execute(
            select(DatasetItemModel).where(DatasetItemModel.dataset_id == dataset_id)
        )
        return [_item_to_domain(row) for row in result.scalars().all()]

    async def get_item(self, item_id: uuid.UUID) -> DatasetItem | None:
        row = await self._session.get(DatasetItemModel, item_id)
        return _item_to_domain(row) if row is not None else None


class SqlAlchemyAppConfigRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, config: AppConfig) -> AppConfig:
        row = AppConfigModel(
            id=config.id,
            project_id=config.project_id,
            name=config.name,
            version=config.version,
            description=config.description,
            prompt=dict(config.prompt),
            model=dict(config.model),
            retrieval=dict(config.retrieval),
            content_hash=config.content_hash,
            created_at=config.created_at,
        )
        self._session.add(row)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            raise
        await self._session.refresh(row)
        return _app_config_to_domain(row)

    async def get_by_id(self, app_config_id: uuid.UUID) -> AppConfig | None:
        row = await self._session.get(AppConfigModel, app_config_id)
        return _app_config_to_domain(row) if row is not None else None

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        *,
        name: str | None = None,
        latest_only: bool = False,
    ) -> list[AppConfig]:
        stmt = select(AppConfigModel).where(AppConfigModel.project_id == project_id)
        if name is not None:
            stmt = stmt.where(AppConfigModel.name == name)
        if latest_only:
            stmt = stmt.distinct(AppConfigModel.name).order_by(
                AppConfigModel.name,
                AppConfigModel.version.desc(),
            )
        else:
            stmt = stmt.order_by(AppConfigModel.created_at.desc())
        result = await self._session.execute(stmt)
        return [_app_config_to_domain(row) for row in result.scalars().all()]

    async def list_versions(self, project_id: uuid.UUID, name: str) -> list[AppConfig]:
        result = await self._session.execute(
            select(AppConfigModel)
            .where(
                AppConfigModel.project_id == project_id,
                AppConfigModel.name == name,
            )
            .order_by(AppConfigModel.version.asc())
        )
        return [_app_config_to_domain(row) for row in result.scalars().all()]

    async def next_version(self, project_id: uuid.UUID, name: str) -> int:
        result = await self._session.execute(
            select(func.coalesce(func.max(AppConfigModel.version), 0) + 1).where(
                AppConfigModel.project_id == project_id,
                AppConfigModel.name == name,
            )
        )
        return int(result.scalar_one())

    async def set_alias(self, alias: AppConfigAlias) -> AppConfigAlias:
        row = await self._session.get(
            AppConfigAliasModel,
            (alias.project_id, alias.name),
        )
        if row is None:
            row = AppConfigAliasModel(
                project_id=alias.project_id,
                name=alias.name,
                app_config_id=alias.app_config_id,
                updated_at=alias.updated_at,
            )
            self._session.add(row)
        else:
            row.app_config_id = alias.app_config_id
            row.updated_at = alias.updated_at
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            raise
        await self._session.refresh(row)
        return _app_config_alias_to_domain(row)

    async def get_alias(self, project_id: uuid.UUID, name: str) -> AppConfigAlias | None:
        row = await self._session.get(AppConfigAliasModel, (project_id, name))
        return _app_config_alias_to_domain(row) if row is not None else None

    async def list_aliases(self, project_id: uuid.UUID) -> list[AppConfigAlias]:
        result = await self._session.execute(
            select(AppConfigAliasModel)
            .where(AppConfigAliasModel.project_id == project_id)
            .order_by(AppConfigAliasModel.name.asc())
        )
        return [_app_config_alias_to_domain(row) for row in result.scalars().all()]

    async def delete_alias(self, project_id: uuid.UUID, name: str) -> bool:
        row = await self._session.get(AppConfigAliasModel, (project_id, name))
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.commit()
        return True


class SqlAlchemyEvaluatorRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, evaluator: Evaluator) -> Evaluator:
        row = EvaluatorModel(
            id=evaluator.id,
            project_id=evaluator.project_id,
            name=evaluator.name,
            type=evaluator.type,
            config=dict(evaluator.config),
            version=evaluator.version,
        )
        self._session.add(row)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            raise
        await self._session.refresh(row)
        return _evaluator_to_domain(row)

    async def get_by_id(self, evaluator_id: uuid.UUID) -> Evaluator | None:
        row = await self._session.get(EvaluatorModel, evaluator_id)
        return _evaluator_to_domain(row) if row is not None else None

    async def list_by_project(self, project_id: uuid.UUID) -> list[Evaluator]:
        result = await self._session.execute(
            select(EvaluatorModel).where(EvaluatorModel.project_id == project_id)
        )
        return [_evaluator_to_domain(row) for row in result.scalars().all()]

    async def get_by_ids(self, evaluator_ids: list[uuid.UUID]) -> list[Evaluator]:
        if not evaluator_ids:
            return []
        result = await self._session.execute(
            select(EvaluatorModel).where(EvaluatorModel.id.in_(evaluator_ids))
        )
        return [_evaluator_to_domain(row) for row in result.scalars().all()]


class SqlAlchemyExperimentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, experiment: Experiment) -> Experiment:
        row = ExperimentModel(
            id=experiment.id,
            project_id=experiment.project_id,
            name=experiment.name,
            dataset_id=experiment.dataset_id,
            model_config_json=dict(experiment.model_config),
            version=experiment.version,
            baseline_experiment_id=experiment.baseline_experiment_id,
            app_config_id=experiment.app_config_id,
            metrics_set_id=experiment.metrics_set_id,
            status=experiment.status,
            created_at=experiment.created_at,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return _experiment_to_domain(row)

    async def get_by_id(self, experiment_id: uuid.UUID) -> Experiment | None:
        row = await self._session.get(ExperimentModel, experiment_id)
        return _experiment_to_domain(row) if row is not None else None

    async def list_by_project(self, project_id: uuid.UUID) -> list[Experiment]:
        result = await self._session.execute(
            select(ExperimentModel)
            .where(ExperimentModel.project_id == project_id)
            .order_by(ExperimentModel.created_at.desc())
        )
        return [_experiment_to_domain(row) for row in result.scalars().all()]

    async def update(self, experiment: Experiment) -> Experiment:
        row = await self._session.get(ExperimentModel, experiment.id)
        if row is None:
            raise ValueError(f"Experiment not found: {experiment.id}")
        row.name = experiment.name
        row.dataset_id = experiment.dataset_id
        row.model_config_json = dict(experiment.model_config)
        row.version = experiment.version
        row.baseline_experiment_id = experiment.baseline_experiment_id
        row.app_config_id = experiment.app_config_id
        row.metrics_set_id = experiment.metrics_set_id
        row.status = experiment.status
        await self._session.commit()
        await self._session.refresh(row)
        return _experiment_to_domain(row)

    async def count_by_metrics_set_id(self, metrics_set_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(ExperimentModel)
            .where(ExperimentModel.metrics_set_id == metrics_set_id)
        )
        return int(result.scalar_one())


class SqlAlchemyEvaluationRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_run(self, run: EvaluationRun) -> EvaluationRun:
        row = EvaluationRunModel(
            id=run.id,
            experiment_id=run.experiment_id,
            evaluator_id=run.evaluator_id,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            metadata_json=dict(run.metadata),
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return _run_to_domain(row)

    async def update_run(self, run: EvaluationRun) -> EvaluationRun:
        row = await self._session.get(EvaluationRunModel, run.id)
        if row is None:
            raise ValueError(f"Evaluation run not found: {run.id}")
        row.status = run.status
        row.started_at = run.started_at
        row.finished_at = run.finished_at
        row.metadata_json = dict(run.metadata)
        await self._session.commit()
        await self._session.refresh(row)
        return _run_to_domain(row)

    async def get_run(self, run_id: uuid.UUID) -> EvaluationRun | None:
        row = await self._session.get(EvaluationRunModel, run_id)
        return _run_to_domain(row) if row is not None else None

    async def list_runs_by_experiment(self, experiment_id: uuid.UUID) -> list[EvaluationRun]:
        result = await self._session.execute(
            select(EvaluationRunModel)
            .where(EvaluationRunModel.experiment_id == experiment_id)
            .order_by(EvaluationRunModel.started_at.desc().nullslast())
        )
        return [_run_to_domain(row) for row in result.scalars().all()]

    async def add_result(self, result: EvaluationResultRecord) -> EvaluationResultRecord:
        row = EvaluationResultModel(
            id=result.id,
            run_id=result.run_id,
            dataset_item_id=result.dataset_item_id,
            score=result.score,
            label=result.label,
            explanation=result.explanation,
            metadata_json=dict(result.metadata),
            duration_ms=result.duration_ms,
        )
        self._session.add(row)
        await self._session.commit()
        await self._session.refresh(row)
        return _result_to_domain(row)

    async def list_results(self, run_id: uuid.UUID) -> list[EvaluationResultRecord]:
        result = await self._session.execute(
            select(EvaluationResultModel).where(EvaluationResultModel.run_id == run_id)
        )
        return [_result_to_domain(row) for row in result.scalars().all()]

    async def add_results(
        self, results: list[EvaluationResultRecord]
    ) -> list[EvaluationResultRecord]:
        rows = [
            EvaluationResultModel(
                id=r.id,
                run_id=r.run_id,
                dataset_item_id=r.dataset_item_id,
                score=r.score,
                label=r.label,
                explanation=r.explanation,
                metadata_json=dict(r.metadata),
                duration_ms=r.duration_ms,
            )
            for r in results
        ]
        self._session.add_all(rows)
        await self._session.commit()
        return [_result_to_domain(row) for row in rows]


def _metrics_set_entry_to_domain(row: MetricsSetEntryModel) -> MetricsSetEntry:
    return MetricsSetEntry(
        id=row.id,
        kind=row.kind,
        enabled=row.enabled,
        threshold=row.threshold,
        config=dict(row.config or {}),
        evaluator_id=row.evaluator_id,
        is_default=row.is_default,
        created_at=row.created_at,
    )


def _metrics_set_to_domain(row: MetricsSetModel) -> MetricsSet:
    sorted_entries = sorted(row.entries, key=lambda e: e.kind)
    entries = tuple(_metrics_set_entry_to_domain(e) for e in sorted_entries)
    return MetricsSet(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        version=row.version,
        description=row.description,
        is_project_default=row.is_project_default,
        created_at=row.created_at,
        updated_at=row.updated_at,
        entries=entries,
    )


def _metrics_set_entry_to_model(
    entry: MetricsSetEntry,
    metrics_set_id: uuid.UUID,
) -> MetricsSetEntryModel:
    return MetricsSetEntryModel(
        id=entry.id,
        metrics_set_id=metrics_set_id,
        kind=entry.kind,
        enabled=entry.enabled,
        threshold=entry.threshold,
        config=dict(entry.config),
        evaluator_id=entry.evaluator_id,
        is_default=entry.is_default,
        created_at=entry.created_at,
    )


def _sync_metrics_set_entries(row: MetricsSetModel, entries: tuple[MetricsSetEntry, ...]) -> None:
    by_kind = {entry.kind: entry for entry in row.entries}
    by_id = {entry.id: entry for entry in row.entries}
    desired_kinds = {entry.kind for entry in entries}
    for kind in list(by_kind.keys()):
        if kind not in desired_kinds:
            row.entries.remove(by_kind[kind])
    for entry in entries:
        existing = by_kind.get(entry.kind) or by_id.get(entry.id)
        if existing is not None:
            existing.kind = entry.kind
            existing.enabled = entry.enabled
            existing.threshold = entry.threshold
            existing.config = dict(entry.config)
            existing.evaluator_id = entry.evaluator_id
            existing.is_default = entry.is_default
        else:
            row.entries.append(_metrics_set_entry_to_model(entry, row.id))


class SqlAlchemyMetricsSetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, metrics_set: MetricsSet) -> MetricsSet:
        row = MetricsSetModel(
            id=metrics_set.id,
            project_id=metrics_set.project_id,
            name=metrics_set.name,
            version=metrics_set.version,
            description=metrics_set.description,
            is_project_default=metrics_set.is_project_default,
            created_at=metrics_set.created_at,
            updated_at=metrics_set.updated_at,
            entries=[
                _metrics_set_entry_to_model(entry, metrics_set.id) for entry in metrics_set.entries
            ],
        )
        self._session.add(row)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            raise
        result = await self._session.execute(
            select(MetricsSetModel)
            .options(selectinload(MetricsSetModel.entries))
            .where(MetricsSetModel.id == metrics_set.id)
        )
        refreshed = result.scalar_one()
        return _metrics_set_to_domain(refreshed)

    async def get_by_id(self, metrics_set_id: uuid.UUID) -> MetricsSet | None:
        result = await self._session.execute(
            select(MetricsSetModel)
            .options(selectinload(MetricsSetModel.entries))
            .where(MetricsSetModel.id == metrics_set_id)
        )
        row = result.scalar_one_or_none()
        return _metrics_set_to_domain(row) if row is not None else None

    async def get_project_default(self, project_id: uuid.UUID) -> MetricsSet | None:
        result = await self._session.execute(
            select(MetricsSetModel)
            .options(selectinload(MetricsSetModel.entries))
            .where(
                MetricsSetModel.project_id == project_id,
                MetricsSetModel.is_project_default.is_(True),
            )
        )
        row = result.scalar_one_or_none()
        return _metrics_set_to_domain(row) if row is not None else None

    async def list_by_project(self, project_id: uuid.UUID) -> list[MetricsSet]:
        result = await self._session.execute(
            select(MetricsSetModel)
            .options(selectinload(MetricsSetModel.entries))
            .where(MetricsSetModel.project_id == project_id)
            .order_by(MetricsSetModel.created_at.asc())
        )
        return [_metrics_set_to_domain(row) for row in result.scalars().all()]

    async def update(self, metrics_set: MetricsSet) -> MetricsSet:
        result = await self._session.execute(
            select(MetricsSetModel)
            .options(selectinload(MetricsSetModel.entries))
            .where(MetricsSetModel.id == metrics_set.id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise ValueError(f"MetricsSet not found: {metrics_set.id}")
        row.name = metrics_set.name
        row.version = metrics_set.version
        row.description = metrics_set.description
        row.is_project_default = metrics_set.is_project_default
        row.updated_at = metrics_set.updated_at
        _sync_metrics_set_entries(row, metrics_set.entries)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            raise
        refreshed = await self.get_by_id(metrics_set.id)
        if refreshed is None:
            raise ValueError(f"MetricsSet not found: {metrics_set.id}")
        return refreshed

    async def delete(self, metrics_set_id: uuid.UUID) -> None:
        row = await self._session.get(MetricsSetModel, metrics_set_id)
        if row is not None:
            await self._session.delete(row)
            await self._session.commit()

    async def next_version(self, project_id: uuid.UUID, name: str) -> int:
        result = await self._session.execute(
            select(func.coalesce(func.max(MetricsSetModel.version), 0) + 1).where(
                MetricsSetModel.project_id == project_id,
                MetricsSetModel.name == name,
            )
        )
        return int(result.scalar_one())


class SqlAlchemyExperimentItemOutputRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, output: ExperimentItemOutput) -> ExperimentItemOutput:
        result = await self._session.execute(
            select(ExperimentItemOutputModel).where(
                ExperimentItemOutputModel.experiment_id == output.experiment_id,
                ExperimentItemOutputModel.dataset_item_id == output.dataset_item_id,
            )
        )
        existing = result.scalar_one_or_none()

        if existing is None:
            row = _experiment_item_output_to_model(output)
            self._session.add(row)
            await self._session.commit()
            await self._session.refresh(row)
            return _experiment_item_output_to_domain(row)

        existing.actual_output = output.actual_output
        existing.context = output.context
        existing.metadata_json = dict(output.metadata)
        existing.updated_at = output.updated_at
        await self._session.commit()
        await self._session.refresh(existing)
        return _experiment_item_output_to_domain(existing)

    async def upsert_many(self, outputs: list[ExperimentItemOutput]) -> list[ExperimentItemOutput]:
        return [await self.upsert(output) for output in outputs]

    async def list_by_experiment(self, experiment_id: uuid.UUID) -> list[ExperimentItemOutput]:
        result = await self._session.execute(
            select(ExperimentItemOutputModel)
            .where(ExperimentItemOutputModel.experiment_id == experiment_id)
            .order_by(ExperimentItemOutputModel.dataset_item_id)
        )
        return [_experiment_item_output_to_domain(row) for row in result.scalars().all()]

    async def get(
        self, experiment_id: uuid.UUID, dataset_item_id: uuid.UUID
    ) -> ExperimentItemOutput | None:
        result = await self._session.execute(
            select(ExperimentItemOutputModel).where(
                ExperimentItemOutputModel.experiment_id == experiment_id,
                ExperimentItemOutputModel.dataset_item_id == dataset_item_id,
            )
        )
        row = result.scalar_one_or_none()
        return _experiment_item_output_to_domain(row) if row is not None else None


def _live_interaction_to_domain(row: LiveInteractionModel) -> LiveInteraction:
    return LiveInteraction(
        id=row.id,
        project_id=row.project_id,
        question=row.question,
        answer=row.answer,
        documents=list(row.documents or []),
        metadata=dict(row.metadata_json or {}),
        external_id=row.external_id,
        judge_status=row.judge_status,
        metrics_set_id=row.metrics_set_id,
        score_warning=row.score_warning,
        error_message=row.error_message,
        created_at=row.created_at,
        scored_at=row.scored_at,
    )


def _live_score_to_domain(row: LiveInteractionScoreModel) -> LiveInteractionScore:
    return LiveInteractionScore(
        id=row.id,
        live_interaction_id=row.live_interaction_id,
        evaluator_id=row.evaluator_id,
        kind=row.kind,
        score=row.score,
        label=row.label,
        explanation=row.explanation,
        threshold=row.threshold,
        created_at=row.created_at,
    )


def _live_review_to_domain(row: LiveReviewModel) -> LiveReview:
    return LiveReview(
        id=row.id,
        live_interaction_id=row.live_interaction_id,
        verdict=row.verdict,
        note=row.note,
        reviewer=row.reviewer,
        created_at=row.created_at,
    )


_EXTERNAL_ID_CONSTRAINT = "uq_live_interactions_project_external_id"


class SqlAlchemyLiveInteractionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, interaction: LiveInteraction) -> LiveInteraction:
        row = LiveInteractionModel(
            id=interaction.id,
            project_id=interaction.project_id,
            question=interaction.question,
            answer=interaction.answer,
            documents=list(interaction.documents),
            metadata_json=dict(interaction.metadata),
            external_id=interaction.external_id,
            judge_status=interaction.judge_status,
            metrics_set_id=interaction.metrics_set_id,
            score_warning=interaction.score_warning,
            error_message=interaction.error_message,
            created_at=interaction.created_at,
            scored_at=interaction.scored_at,
        )
        self._session.add(row)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            if interaction.external_id is not None and _EXTERNAL_ID_CONSTRAINT in str(exc.orig):
                raise DuplicateExternalIdError(interaction.external_id) from exc
            raise
        await self._session.refresh(row)
        return _live_interaction_to_domain(row)

    async def update(self, interaction: LiveInteraction) -> LiveInteraction:
        row = await self._session.get(LiveInteractionModel, interaction.id)
        if row is None:
            raise ValueError(f"LiveInteraction not found: {interaction.id}")
        row.question = interaction.question
        row.answer = interaction.answer
        row.documents = list(interaction.documents)
        row.metadata_json = dict(interaction.metadata)
        row.external_id = interaction.external_id
        row.judge_status = interaction.judge_status
        row.metrics_set_id = interaction.metrics_set_id
        row.score_warning = interaction.score_warning
        row.error_message = interaction.error_message
        row.scored_at = interaction.scored_at
        await self._session.commit()
        await self._session.refresh(row)
        return _live_interaction_to_domain(row)

    async def get_by_id(self, interaction_id: uuid.UUID) -> LiveInteraction | None:
        row = await self._session.get(LiveInteractionModel, interaction_id)
        return _live_interaction_to_domain(row) if row is not None else None

    async def get_by_external_id(
        self, project_id: uuid.UUID, external_id: str
    ) -> LiveInteraction | None:
        result = await self._session.execute(
            select(LiveInteractionModel).where(
                LiveInteractionModel.project_id == project_id,
                LiveInteractionModel.external_id == external_id,
            )
        )
        row = result.scalar_one_or_none()
        return _live_interaction_to_domain(row) if row is not None else None

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        *,
        judge_status: str | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[LiveInteraction]:
        stmt = select(LiveInteractionModel).where(LiveInteractionModel.project_id == project_id)
        if judge_status is not None:
            stmt = stmt.where(LiveInteractionModel.judge_status == judge_status)
        if search:
            pattern = f"%{escape_like(search.strip())}%"
            stmt = stmt.where(LiveInteractionModel.question.ilike(pattern, escape="\\"))
        # id tiebreak keeps pages stable when created_at collides.
        stmt = (
            stmt.order_by(LiveInteractionModel.created_at.desc(), LiveInteractionModel.id.desc())
            .offset(max(0, offset))
            .limit(max(1, min(limit, 200)))
        )
        result = await self._session.execute(stmt)
        return [_live_interaction_to_domain(row) for row in result.scalars().all()]

    async def replace_scores(
        self, interaction_id: uuid.UUID, scores: list[LiveInteractionScore]
    ) -> list[LiveInteractionScore]:
        existing = await self._session.execute(
            select(LiveInteractionScoreModel).where(
                LiveInteractionScoreModel.live_interaction_id == interaction_id
            )
        )
        for row in existing.scalars().all():
            await self._session.delete(row)
        await self._session.flush()
        saved: list[LiveInteractionScore] = []
        for score in scores:
            row = LiveInteractionScoreModel(
                id=score.id,
                live_interaction_id=score.live_interaction_id,
                evaluator_id=score.evaluator_id,
                kind=score.kind,
                score=score.score,
                label=score.label,
                explanation=score.explanation,
                threshold=score.threshold,
                created_at=score.created_at,
            )
            self._session.add(row)
            saved.append(score)
        await self._session.commit()
        return saved

    async def list_scores(self, interaction_id: uuid.UUID) -> list[LiveInteractionScore]:
        result = await self._session.execute(
            select(LiveInteractionScoreModel)
            .where(LiveInteractionScoreModel.live_interaction_id == interaction_id)
            .order_by(LiveInteractionScoreModel.created_at.asc())
        )
        return [_live_score_to_domain(row) for row in result.scalars().all()]

    async def upsert_review(self, review: LiveReview) -> LiveReview:
        result = await self._session.execute(
            select(LiveReviewModel).where(
                LiveReviewModel.live_interaction_id == review.live_interaction_id
            )
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            row = LiveReviewModel(
                id=review.id,
                live_interaction_id=review.live_interaction_id,
                verdict=review.verdict,
                note=review.note,
                reviewer=review.reviewer,
                created_at=review.created_at,
            )
            self._session.add(row)
            await self._session.commit()
            await self._session.refresh(row)
            return _live_review_to_domain(row)
        existing.verdict = review.verdict
        existing.note = review.note
        existing.reviewer = review.reviewer
        existing.created_at = review.created_at
        await self._session.commit()
        await self._session.refresh(existing)
        return _live_review_to_domain(existing)

    async def get_review(self, interaction_id: uuid.UUID) -> LiveReview | None:
        result = await self._session.execute(
            select(LiveReviewModel).where(LiveReviewModel.live_interaction_id == interaction_id)
        )
        row = result.scalar_one_or_none()
        return _live_review_to_domain(row) if row is not None else None

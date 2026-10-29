from __future__ import annotations

import builtins
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import httpx2

from opengrade._config import resolve_project_id
from opengrade._http import _HttpTransport, read_upload, resolve_api_base_url
from opengrade.models import (
    DatasetDetailResponse,
    DatasetItemResponse,
    DatasetResponse,
    EvaluateResponse,
    EvaluationRunResponse,
    ExperimentAliasEventResponse,
    ExperimentAliasResponse,
    ExperimentCompareResponse,
    ExperimentItemOutputResponse,
    ExperimentMetricsResponse,
    ExperimentResponse,
    ExperimentSummaryResponse,
    HealthResponse,
    ImportDatasetItemsResponse,
    ListLiveInteractionsResponse,
    LiveInteractionResponse,
    MetricsPackResponse,
    MetricsSetResponse,
    ProjectResponse,
    TraceScoresAccepted,
    UpsertExperimentOutputsResponse,
)
from opengrade.registry import AppConfigClient

_TERMINAL_EXPERIMENT_STATUSES = frozenset({"completed", "failed", "cancelled"})


class _ProjectsResource:
    def __init__(self, http: _HttpTransport) -> None:
        self._http = http

    def create(self, *, name: str, slug: str | None = None) -> ProjectResponse:
        body: dict[str, Any] = {"name": name}
        if slug is not None:
            body["slug"] = slug
        return self._http.request_model(
            "POST", "/api/v1/projects", body=body, response_model=ProjectResponse
        )

    def list(self) -> builtins.list[ProjectResponse]:
        return self._http.request_model_list(
            "GET", "/api/v1/projects", response_model=ProjectResponse
        )

    def get(self, project_id: str | None = None) -> ProjectResponse:
        project_id = resolve_project_id(project_id)
        return self._http.request_model(
            "GET",
            f"/api/v1/projects/{project_id}",
            response_model=ProjectResponse,
        )


class _DatasetsResource:
    def __init__(self, http: _HttpTransport) -> None:
        self._http = http

    def create(
        self,
        project_id: str | None = None,
        *,
        name: str,
        version: int = 1,
        description: str | None = None,
        task_type: str = "rag_qa",
    ) -> DatasetResponse:
        project_id = resolve_project_id(project_id)
        body: dict[str, Any] = {
            "name": name,
            "version": version,
            "task_type": task_type,
        }
        if description is not None:
            body["description"] = description
        return self._http.request_model(
            "POST",
            f"/api/v1/projects/{project_id}/datasets",
            body=body,
            response_model=DatasetResponse,
        )

    def list(
        self, project_id: str | None = None, *, task_type: str | None = None
    ) -> builtins.list[DatasetResponse]:
        project_id = resolve_project_id(project_id)
        query: dict[str, str] | None = None
        if task_type is not None:
            query = {"task_type": task_type}
        return self._http.request_model_list(
            "GET",
            f"/api/v1/projects/{project_id}/datasets",
            query=query,
            response_model=DatasetResponse,
        )

    def get(self, dataset_id: str) -> DatasetDetailResponse:
        return self._http.request_model(
            "GET",
            f"/api/v1/datasets/{dataset_id}",
            response_model=DatasetDetailResponse,
        )

    def add_item(
        self,
        dataset_id: str,
        *,
        input: Any,
        expected_output: Any = None,
        actual_output: Any = None,
        context: Any = None,
        metadata: dict[str, Any] | None = None,
        source_trace_id: str | None = None,
        source_span_id: str | None = None,
    ) -> DatasetItemResponse:
        body: dict[str, Any] = {"input": input}
        if expected_output is not None:
            body["expected_output"] = expected_output
        if actual_output is not None:
            body["actual_output"] = actual_output
        if context is not None:
            body["context"] = context
        if metadata is not None:
            body["metadata"] = metadata
        if source_trace_id is not None:
            body["source_trace_id"] = source_trace_id
        if source_span_id is not None:
            body["source_span_id"] = source_span_id
        return self._http.request_model(
            "POST",
            f"/api/v1/datasets/{dataset_id}/items",
            body=body,
            response_model=DatasetItemResponse,
        )

    def create_with_items(
        self,
        project_id: str | None = None,
        *,
        name: str,
        items: builtins.list[dict[str, Any]],
        version: int = 1,
        description: str | None = None,
        task_type: str = "rag_qa",
    ) -> DatasetResponse:
        project_id = resolve_project_id(project_id)
        dataset = self.create(
            project_id,
            name=name,
            version=version,
            description=description,
            task_type=task_type,
        )
        dataset_id = str(dataset.id)
        self._add_items_from(dataset_id, items, start=0)
        return dataset

    def _add_items_from(
        self,
        dataset_id: str,
        items: builtins.list[dict[str, Any]],
        *,
        start: int,
    ) -> None:
        """Append ``items[start:]``; leaves a prefix dataset on mid-loop failure."""
        for item in items[start:]:
            self.add_item(dataset_id, **item)

    def ensure_items(
        self,
        dataset_id: str,
        items: builtins.list[dict[str, Any]],
    ) -> int:
        """Resume uploading until the dataset has ``len(items)`` rows; return stored count."""
        detail = self.get(dataset_id)
        have = len(detail.items)
        if have >= len(items):
            return have
        self._add_items_from(dataset_id, items, start=have)
        return len(items)

    def import_items(
        self,
        dataset_id: str,
        *,
        path: str | Path | None = None,
        file: tuple[str, bytes] | None = None,
        format: str | None = None,
        content_type: str | None = None,
    ) -> ImportDatasetItemsResponse:
        filename, content = read_upload(path, file=file)
        query: dict[str, str] | None = None
        if format is not None:
            query = {"format": format}
        return self._http.request_multipart_model(
            "POST",
            f"/api/v1/datasets/{dataset_id}/items/import",
            response_model=ImportDatasetItemsResponse,
            file_field="file",
            filename=filename,
            content=content,
            content_type=content_type,
            query=query,
        )


class _ExperimentsResource:
    def __init__(self, http: _HttpTransport) -> None:
        self._http = http

    def create(
        self,
        project_id: str | None = None,
        *,
        name: str,
        dataset_id: str,
        model_config: dict[str, Any] | None = None,
        version: str | None = None,
        baseline_experiment_id: str | None = None,
        app_config_id: str | None = None,
        app_config_alias: str | None = None,
        metrics_set_id: str | None = None,
    ) -> ExperimentResponse:
        project_id = resolve_project_id(project_id)
        body: dict[str, Any] = {
            "name": name,
            "dataset_id": dataset_id,
            "model_config": model_config or {},
        }
        if version is not None:
            body["version"] = version
        if baseline_experiment_id is not None:
            body["baseline_experiment_id"] = baseline_experiment_id
        if app_config_id is not None:
            body["app_config_id"] = app_config_id
        if app_config_alias is not None:
            body["app_config_alias"] = app_config_alias
        if metrics_set_id is not None:
            body["metrics_set_id"] = metrics_set_id
        return self._http.request_model(
            "POST",
            f"/api/v1/projects/{project_id}/experiments",
            body=body,
            response_model=ExperimentResponse,
        )

    def list(self, project_id: str | None = None) -> builtins.list[ExperimentResponse]:
        project_id = resolve_project_id(project_id)
        return self._http.request_model_list(
            "GET",
            f"/api/v1/projects/{project_id}/experiments",
            response_model=ExperimentResponse,
        )

    def get(self, experiment_id: str) -> ExperimentResponse:
        return self._http.request_model(
            "GET",
            f"/api/v1/experiments/{experiment_id}",
            response_model=ExperimentResponse,
        )

    def set_alias(
        self,
        alias: str,
        experiment_id: str,
        *,
        project_id: str | None = None,
        note: str | None = None,
        force: bool = False,
    ) -> ExperimentAliasResponse:
        project_id = resolve_project_id(project_id)
        body: dict[str, Any] = {"experiment_id": experiment_id}
        if note is not None:
            body["note"] = note
        if force:
            body["force"] = True
        return self._http.request_model(
            "PUT",
            f"/api/v1/projects/{project_id}/experiment-aliases/{quote(alias, safe='')}",
            body=body,
            response_model=ExperimentAliasResponse,
        )

    def get_alias(self, alias: str, *, project_id: str | None = None) -> ExperimentAliasResponse:
        project_id = resolve_project_id(project_id)
        return self._http.request_model(
            "GET",
            f"/api/v1/projects/{project_id}/experiment-aliases/{quote(alias, safe='')}",
            response_model=ExperimentAliasResponse,
        )

    def list_aliases(self, project_id: str | None = None) -> builtins.list[ExperimentAliasResponse]:
        project_id = resolve_project_id(project_id)
        return self._http.request_model_list(
            "GET",
            f"/api/v1/projects/{project_id}/experiment-aliases",
            response_model=ExperimentAliasResponse,
        )

    def alias_history(
        self, alias: str, *, project_id: str | None = None, limit: int = 50
    ) -> builtins.list[ExperimentAliasEventResponse]:
        project_id = resolve_project_id(project_id)
        return self._http.request_model_list(
            "GET",
            f"/api/v1/projects/{project_id}/experiment-aliases/{quote(alias, safe='')}/history",
            response_model=ExperimentAliasEventResponse,
            query={"limit": str(limit)},
        )

    def delete_alias(self, alias: str, *, project_id: str | None = None) -> None:
        project_id = resolve_project_id(project_id)
        self._http.request(
            "DELETE",
            f"/api/v1/projects/{project_id}/experiment-aliases/{quote(alias, safe='')}",
        )

    def list_outputs(self, experiment_id: str) -> builtins.list[ExperimentItemOutputResponse]:
        return self._http.request_model_list(
            "GET",
            f"/api/v1/experiments/{experiment_id}/outputs",
            response_model=ExperimentItemOutputResponse,
        )

    def upsert_outputs(
        self, experiment_id: str, items: builtins.list[dict[str, Any]]
    ) -> UpsertExperimentOutputsResponse:
        """Write per-item outputs; keys left out of an item keep their stored value."""
        return self._http.request_model(
            "PUT",
            f"/api/v1/experiments/{experiment_id}/outputs",
            body={"items": items},
            response_model=UpsertExperimentOutputsResponse,
        )

    def submit_client_results(
        self, experiment_id: str, metrics: builtins.list[dict[str, Any]]
    ) -> builtins.list[EvaluationRunResponse]:
        """Store scores computed client-side: one evaluation run per metric.

        Each metric is ``{"name", "results": [{"dataset_item_id", "score", "label",
        "explanation", "metadata"}], "threshold"?, "config"?}``. Bump ``config`` when
        the metric code changes so compare flags it instead of reporting a delta.
        """
        return self._http.request_model_list(
            "POST",
            f"/api/v1/experiments/{experiment_id}/client-results",
            body={"metrics": metrics},
            response_model=EvaluationRunResponse,
        )

    def log_metrics(self, experiment_id: str, metrics: Mapping[str, float]) -> dict[str, float]:
        """Upsert experiment-level scalars (last value per key wins); returns all of them."""
        response = self._http.request_model(
            "PUT",
            f"/api/v1/experiments/{experiment_id}/metrics",
            body={"metrics": dict(metrics)},
            response_model=ExperimentMetricsResponse,
        )
        return dict(response.metrics)

    def get_metrics(self, experiment_id: str) -> dict[str, float]:
        response = self._http.request_model(
            "GET",
            f"/api/v1/experiments/{experiment_id}/metrics",
            response_model=ExperimentMetricsResponse,
        )
        return dict(response.metrics)

    def update_params(self, experiment_id: str, params: Mapping[str, Any]) -> ExperimentResponse:
        """Merge ``params`` into ``model_config``.

        The server answers 409 once an evaluation has started or the experiment has
        evaluation runs, or when it was created from an app config.
        """
        return self._http.request_model(
            "PATCH",
            f"/api/v1/experiments/{experiment_id}/params",
            body={"params": dict(params)},
            response_model=ExperimentResponse,
        )

    def evaluate_pack(
        self,
        experiment_id: str,
        *,
        metrics_set_id: str | None = None,
        save_as_default: bool = False,
        poll_interval: float = 1.0,
        timeout: float = 600.0,
    ) -> EvaluateResponse:
        """Start pack scoring (202) and poll until the experiment finishes."""
        body: dict[str, Any] = {}
        if metrics_set_id is not None:
            body["metrics_set_id"] = metrics_set_id
        if save_as_default:
            body["save_as_default"] = True
        self._http.request_model(
            "POST",
            f"/api/v1/experiments/{experiment_id}/evaluate-pack",
            body=body or None,
            response_model=ExperimentResponse,
        )
        experiment = self._wait_until_scored(
            experiment_id, poll_interval=poll_interval, timeout=timeout
        )
        runs = self._http.request_model_list(
            "GET",
            f"/api/v1/experiments/{experiment_id}/runs",
            response_model=EvaluationRunResponse,
        )
        detailed: builtins.list[EvaluationRunResponse] = []
        for run in runs:
            detailed.append(
                self._http.request_model(
                    "GET",
                    f"/api/v1/evaluation-runs/{run.id}",
                    response_model=EvaluationRunResponse,
                )
            )
        return EvaluateResponse(experiment=experiment, runs=detailed)

    def _wait_until_scored(
        self,
        experiment_id: str,
        *,
        poll_interval: float,
        timeout: float,
    ) -> ExperimentResponse:
        deadline = time.monotonic() + timeout
        while True:
            experiment = self.get(experiment_id)
            status = (experiment.status or "").lower()
            if status in _TERMINAL_EXPERIMENT_STATUSES:
                return experiment
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Timed out waiting for experiment {experiment_id} "
                    f"to leave status={experiment.status!r}"
                )
            time.sleep(poll_interval)

    def summary(
        self,
        experiment_id: str,
        *,
        run_ids: builtins.list[str] | None = None,
        evaluator_ids: builtins.list[str] | None = None,
    ) -> ExperimentSummaryResponse:
        path = f"/api/v1/experiments/{experiment_id}/summary"
        pairs: builtins.list[tuple[str, str]] = []
        for rid in run_ids or []:
            pairs.append(("run_ids", rid))
        for eid in evaluator_ids or []:
            pairs.append(("evaluator_ids", eid))
        if pairs:
            path = f"{path}?{urlencode(pairs)}"
        return self._http.request_model("GET", path, response_model=ExperimentSummaryResponse)

    def compare(
        self,
        experiment_id: str,
        baseline_id: str,
        *,
        evaluator_ids: builtins.list[str] | None = None,
        candidate_run_ids: builtins.list[str] | None = None,
        baseline_run_ids: builtins.list[str] | None = None,
    ) -> ExperimentCompareResponse:
        path = f"/api/v1/experiments/{experiment_id}/compare/{baseline_id}"
        pairs: builtins.list[tuple[str, str]] = []
        for eid in evaluator_ids or []:
            pairs.append(("evaluator_ids", eid))
        for rid in candidate_run_ids or []:
            pairs.append(("candidate_run_ids", rid))
        for rid in baseline_run_ids or []:
            pairs.append(("baseline_run_ids", rid))
        if pairs:
            path = f"{path}?{urlencode(pairs)}"
        return self._http.request_model("GET", path, response_model=ExperimentCompareResponse)


class _MetricsPacksResource:
    def __init__(self, http: _HttpTransport) -> None:
        self._http = http

    def ensure(self, project_id: str | None = None) -> MetricsPackResponse:
        project_id = resolve_project_id(project_id)
        return self._http.request_model(
            "POST",
            f"/api/v1/projects/{project_id}/metrics-pack/ensure",
            body={},
            response_model=MetricsPackResponse,
        )

    def get(self, project_id: str | None = None) -> MetricsPackResponse:
        project_id = resolve_project_id(project_id)
        return self._http.request_model(
            "GET",
            f"/api/v1/projects/{project_id}/metrics-pack",
            response_model=MetricsPackResponse,
        )


class _MetricsSetsResource:
    def __init__(self, http: _HttpTransport) -> None:
        self._http = http

    def list(self, project_id: str | None = None) -> builtins.list[MetricsSetResponse]:
        project_id = resolve_project_id(project_id)
        return self._http.request_model_list(
            "GET",
            f"/api/v1/projects/{project_id}/metrics-sets",
            response_model=MetricsSetResponse,
        )

    def get(self, metrics_set_id: str) -> MetricsSetResponse:
        return self._http.request_model(
            "GET",
            f"/api/v1/metrics-sets/{metrics_set_id}",
            response_model=MetricsSetResponse,
        )

    def create(
        self,
        project_id: str | None = None,
        *,
        name: str,
        entries: builtins.list[dict[str, Any]],
        description: str | None = None,
    ) -> MetricsSetResponse:
        project_id = resolve_project_id(project_id)
        body: dict[str, Any] = {"name": name, "entries": entries}
        if description is not None:
            body["description"] = description
        return self._http.request_model(
            "POST",
            f"/api/v1/projects/{project_id}/metrics-sets",
            body=body,
            response_model=MetricsSetResponse,
        )


class _LiveRunsResource:
    def __init__(self, http: _HttpTransport) -> None:
        self._http = http

    def submit(
        self,
        project_id: str | None = None,
        *,
        question: str,
        answer: str,
        documents: builtins.list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
        external_id: str | None = None,
        metrics_set_id: str | None = None,
    ) -> LiveInteractionResponse:
        project_id = resolve_project_id(project_id)
        body: dict[str, Any] = {
            "question": question,
            "answer": answer,
            "documents": list(documents or []),
            "metadata": dict(metadata or {}),
        }
        if external_id is not None:
            body["external_id"] = external_id
        if metrics_set_id is not None:
            body["metrics_set_id"] = metrics_set_id
        return self._http.request_model(
            "POST",
            f"/api/v1/projects/{project_id}/live-interactions",
            body=body,
            response_model=LiveInteractionResponse,
        )

    def list(
        self,
        project_id: str | None = None,
        *,
        judge_status: str | None = None,
        search: str | None = None,
        failed_only: bool = False,
        limit: int = 50,
    ) -> ListLiveInteractionsResponse:
        project_id = resolve_project_id(project_id)
        params: dict[str, str] = {"limit": str(limit)}
        if judge_status is not None:
            params["judge_status"] = judge_status
        if search is not None:
            params["search"] = search
        if failed_only:
            params["failed_only"] = "true"
        path = f"/api/v1/projects/{project_id}/live-interactions?{urlencode(params)}"
        return self._http.request_model("GET", path, response_model=ListLiveInteractionsResponse)

    def get(self, interaction_id: str) -> LiveInteractionResponse:
        return self._http.request_model(
            "GET",
            f"/api/v1/live-interactions/{interaction_id}",
            response_model=LiveInteractionResponse,
        )

    def promote(
        self,
        interaction_id: str,
        *,
        dataset_id: str,
        expected_output: Any,
        expected_doc_ids: builtins.list[str] | None = None,
    ) -> DatasetItemResponse:
        body: dict[str, Any] = {
            "dataset_id": dataset_id,
            "expected_output": expected_output,
        }
        if expected_doc_ids is not None:
            body["expected_doc_ids"] = list(expected_doc_ids)
        return self._http.request_model(
            "POST",
            f"/api/v1/live-interactions/{interaction_id}/promote",
            body=body,
            response_model=DatasetItemResponse,
        )

    def rescore(self, interaction_id: str) -> LiveInteractionResponse:
        return self._http.request_model(
            "POST",
            f"/api/v1/live-interactions/{interaction_id}/rescore",
            body={},
            response_model=LiveInteractionResponse,
        )


class _TraceScoresResource:
    def __init__(self, http: _HttpTransport) -> None:
        self._http = http

    def log(
        self, project_id: str | None, scores: builtins.list[dict[str, Any]]
    ) -> TraceScoresAccepted:
        """Upsert scores on traces: ``{"trace_id", "name", "value"?, "label"?,
        "explanation"?, "threshold"?, "source"?, "author"?, "metadata"?}`` (max 500)."""
        project_id = resolve_project_id(project_id)
        return self._http.request_model(
            "POST",
            f"/api/v1/projects/{project_id}/trace-scores",
            body={"scores": scores},
            response_model=TraceScoresAccepted,
        )


class Client:
    """Platform control-plane client (projects, datasets, experiments, …)."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = 30.0,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        resolved = resolve_api_base_url(base_url)
        self._http = _HttpTransport(resolved, timeout=timeout, transport=transport)
        self.base_url = resolved
        self.projects = _ProjectsResource(self._http)
        self.datasets = _DatasetsResource(self._http)
        self.experiments = _ExperimentsResource(self._http)
        self.metrics_packs = _MetricsPacksResource(self._http)
        self.metrics_sets = _MetricsSetsResource(self._http)
        self.live_runs = _LiveRunsResource(self._http)
        self.trace_scores = _TraceScoresResource(self._http)
        self.app_configs = AppConfigClient.from_transport(self._http)

    def health(self) -> HealthResponse:
        return self._http.request_model("GET", "/health", response_model=HealthResponse)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

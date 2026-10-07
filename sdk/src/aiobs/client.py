from __future__ import annotations

import builtins
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx2

from aiobs._http import _HttpTransport, read_upload, resolve_api_base_url
from aiobs.registry import AppConfigClient


class _ProjectsResource:
    def __init__(self, http: _HttpTransport) -> None:
        self._http = http

    def create(self, *, name: str, slug: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"name": name}
        if slug is not None:
            body["slug"] = slug
        result = self._http.request("POST", "/api/v1/projects", body=body)
        assert isinstance(result, dict)
        return result

    def list(self) -> builtins.list[dict[str, Any]]:
        result = self._http.request("GET", "/api/v1/projects")
        assert isinstance(result, builtins.list)
        return result

    def get(self, project_id: str) -> dict[str, Any]:
        result = self._http.request("GET", f"/api/v1/projects/{project_id}")
        assert isinstance(result, dict)
        return result


class _DatasetsResource:
    def __init__(self, http: _HttpTransport) -> None:
        self._http = http

    def create(
        self,
        project_id: str,
        *,
        name: str,
        version: int = 1,
        description: str | None = None,
        task_type: str = "rag_qa",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "name": name,
            "version": version,
            "task_type": task_type,
        }
        if description is not None:
            body["description"] = description
        result = self._http.request(
            "POST",
            f"/api/v1/projects/{project_id}/datasets",
            body=body,
        )
        assert isinstance(result, dict)
        return result

    def list(
        self, project_id: str, *, task_type: str | None = None
    ) -> builtins.list[dict[str, Any]]:
        query: dict[str, str] | None = None
        if task_type is not None:
            query = {"task_type": task_type}
        result = self._http.request(
            "GET",
            f"/api/v1/projects/{project_id}/datasets",
            query=query,
        )
        assert isinstance(result, builtins.list)
        return result

    def get(self, dataset_id: str) -> dict[str, Any]:
        result = self._http.request("GET", f"/api/v1/datasets/{dataset_id}")
        assert isinstance(result, dict)
        return result

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
    ) -> dict[str, Any]:
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
        result = self._http.request(
            "POST",
            f"/api/v1/datasets/{dataset_id}/items",
            body=body,
        )
        assert isinstance(result, dict)
        return result

    def create_with_items(
        self,
        project_id: str,
        *,
        name: str,
        items: builtins.list[dict[str, Any]],
        version: int = 1,
        description: str | None = None,
        task_type: str = "rag_qa",
    ) -> dict[str, Any]:
        dataset = self.create(
            project_id,
            name=name,
            version=version,
            description=description,
            task_type=task_type,
        )
        dataset_id = str(dataset["id"])
        for item in items:
            self.add_item(dataset_id, **item)
        return dataset

    def import_items(
        self,
        dataset_id: str,
        *,
        path: str | Path | None = None,
        file: tuple[str, bytes] | None = None,
        format: str | None = None,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        filename, content = read_upload(path, file=file)
        query: dict[str, str] | None = None
        if format is not None:
            query = {"format": format}
        result = self._http.request_multipart(
            "POST",
            f"/api/v1/datasets/{dataset_id}/items/import",
            file_field="file",
            filename=filename,
            content=content,
            content_type=content_type,
            query=query,
        )
        assert isinstance(result, dict)
        return result


class _ExperimentsResource:
    def __init__(self, http: _HttpTransport) -> None:
        self._http = http

    def create(
        self,
        project_id: str,
        *,
        name: str,
        dataset_id: str,
        model_config: dict[str, Any] | None = None,
        version: str | None = None,
        baseline_experiment_id: str | None = None,
        app_config_id: str | None = None,
        app_config_alias: str | None = None,
        metrics_set_id: str | None = None,
    ) -> dict[str, Any]:
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
        result = self._http.request(
            "POST",
            f"/api/v1/projects/{project_id}/experiments",
            body=body,
        )
        assert isinstance(result, dict)
        return result

    def list(self, project_id: str) -> builtins.list[dict[str, Any]]:
        result = self._http.request(
            "GET",
            f"/api/v1/projects/{project_id}/experiments",
        )
        assert isinstance(result, builtins.list)
        return result

    def get(self, experiment_id: str) -> dict[str, Any]:
        result = self._http.request("GET", f"/api/v1/experiments/{experiment_id}")
        assert isinstance(result, dict)
        return result

    def list_outputs(self, experiment_id: str) -> builtins.list[dict[str, Any]]:
        result = self._http.request(
            "GET",
            f"/api/v1/experiments/{experiment_id}/outputs",
        )
        assert isinstance(result, builtins.list)
        return result

    def evaluate_pack(
        self,
        experiment_id: str,
        *,
        metrics_set_id: str | None = None,
        save_as_default: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if metrics_set_id is not None:
            body["metrics_set_id"] = metrics_set_id
        if save_as_default:
            body["save_as_default"] = True
        result = self._http.request(
            "POST",
            f"/api/v1/experiments/{experiment_id}/evaluate-pack",
            body=body or None,
        )
        assert isinstance(result, dict)
        return result

    def summary(
        self,
        experiment_id: str,
        *,
        run_ids: builtins.list[str] | None = None,
        evaluator_ids: builtins.list[str] | None = None,
    ) -> dict[str, Any]:
        path = f"/api/v1/experiments/{experiment_id}/summary"
        pairs: builtins.list[tuple[str, str]] = []
        for rid in run_ids or []:
            pairs.append(("run_ids", rid))
        for eid in evaluator_ids or []:
            pairs.append(("evaluator_ids", eid))
        if pairs:
            path = f"{path}?{urlencode(pairs)}"
        result = self._http.request("GET", path)
        assert isinstance(result, dict)
        return result

    def compare(
        self,
        experiment_id: str,
        baseline_id: str,
        *,
        evaluator_ids: builtins.list[str] | None = None,
        candidate_run_ids: builtins.list[str] | None = None,
        baseline_run_ids: builtins.list[str] | None = None,
    ) -> dict[str, Any]:
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
        result = self._http.request("GET", path)
        assert isinstance(result, dict)
        return result


class _MetricsPacksResource:
    def __init__(self, http: _HttpTransport) -> None:
        self._http = http

    def ensure(self, project_id: str) -> dict[str, Any]:
        result = self._http.request(
            "POST",
            f"/api/v1/projects/{project_id}/metrics-pack/ensure",
            body={},
        )
        assert isinstance(result, dict)
        return result

    def get(self, project_id: str) -> dict[str, Any]:
        result = self._http.request(
            "GET",
            f"/api/v1/projects/{project_id}/metrics-pack",
        )
        assert isinstance(result, dict)
        return result


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
        self.app_configs = AppConfigClient(resolved, timeout=timeout, transport=transport)

    def health(self) -> dict[str, Any]:
        result = self._http.request("GET", "/health")
        assert isinstance(result, dict)
        return result

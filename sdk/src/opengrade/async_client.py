from __future__ import annotations

import builtins
from typing import Any
from urllib.parse import urlencode

import httpx2

from opengrade._client_resolve import ProjectResolver, resolve_bound_project
from opengrade._http import _AsyncHttpTransport, resolve_api_base_url
from opengrade.models import (
    DatasetItemResponse,
    HealthResponse,
    ListLiveInteractionsResponse,
    LiveInteractionResponse,
    ProjectResponse,
    TraceScoresAccepted,
)


class _AsyncProjectsResource:
    def __init__(self, http: _AsyncHttpTransport, project: ProjectResolver) -> None:
        self._http = http
        self._project = project

    async def create(self, *, name: str, slug: str | None = None) -> ProjectResponse:
        body: dict[str, Any] = {"name": name}
        if slug is not None:
            body["slug"] = slug
        return await self._http.request_model(
            "POST", "/api/v1/projects", body=body, response_model=ProjectResponse
        )

    async def list(
        self,
        *,
        slug: str | None = None,
        name: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> builtins.list[ProjectResponse]:
        query: dict[str, str] = {}
        if slug is not None:
            query["slug"] = slug
        if name is not None:
            query["name"] = name
        if limit is not None:
            query["limit"] = str(limit)
        if offset:
            query["offset"] = str(offset)
        return await self._http.request_model_list(
            "GET",
            "/api/v1/projects",
            query=query or None,
            response_model=ProjectResponse,
        )

    async def get_by_slug(self, slug: str) -> ProjectResponse:
        from urllib.parse import quote

        return await self._http.request_model(
            "GET",
            f"/api/v1/projects/by-slug/{quote(slug, safe='')}",
            response_model=ProjectResponse,
        )

    async def get(self, project_id: str | None = None) -> ProjectResponse:
        project_id = self._project(project_id)
        return await self._http.request_model(
            "GET",
            f"/api/v1/projects/{project_id}",
            response_model=ProjectResponse,
        )


class _AsyncLiveRunsResource:
    def __init__(self, http: _AsyncHttpTransport, project: ProjectResolver) -> None:
        self._http = http
        self._project = project

    async def submit(
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
        project_id = self._project(project_id)
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
        return await self._http.request_model(
            "POST",
            f"/api/v1/projects/{project_id}/live-interactions",
            body=body,
            response_model=LiveInteractionResponse,
        )

    async def list(
        self,
        project_id: str | None = None,
        *,
        judge_status: str | None = None,
        search: str | None = None,
        failed_only: bool = False,
        since: str | None = None,
        until: str | None = None,
        metadata: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ListLiveInteractionsResponse:
        project_id = self._project(project_id)
        params: list[tuple[str, str]] = [("limit", str(limit)), ("offset", str(offset))]
        if judge_status is not None:
            params.append(("judge_status", judge_status))
        if search is not None:
            params.append(("search", search))
        if failed_only:
            params.append(("failed_only", "true"))
        if since is not None:
            params.append(("since", since))
        if until is not None:
            params.append(("until", until))
        for pair in metadata or ():
            params.append(("metadata", pair))
        path = f"/api/v1/projects/{project_id}/live-interactions?{urlencode(params)}"
        return await self._http.request_model(
            "GET", path, response_model=ListLiveInteractionsResponse
        )

    async def get(self, interaction_id: str) -> LiveInteractionResponse:
        return await self._http.request_model(
            "GET",
            f"/api/v1/live-interactions/{interaction_id}",
            response_model=LiveInteractionResponse,
        )

    async def promote(
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
        return await self._http.request_model(
            "POST",
            f"/api/v1/live-interactions/{interaction_id}/promote",
            body=body,
            response_model=DatasetItemResponse,
        )

    async def rescore(self, interaction_id: str) -> LiveInteractionResponse:
        return await self._http.request_model(
            "POST",
            f"/api/v1/live-interactions/{interaction_id}/rescore",
            body={},
            response_model=LiveInteractionResponse,
        )


class _AsyncTraceScoresResource:
    def __init__(self, http: _AsyncHttpTransport, project: ProjectResolver) -> None:
        self._http = http
        self._project = project

    async def log(
        self, project_id: str | None, scores: builtins.list[dict[str, Any]]
    ) -> TraceScoresAccepted:
        """Upsert scores on traces (same payload as sync ``Client.trace_scores.log``)."""
        project_id = self._project(project_id)
        return await self._http.request_model(
            "POST",
            f"/api/v1/projects/{project_id}/trace-scores",
            body={"scores": scores},
            response_model=TraceScoresAccepted,
        )


class AsyncClient:
    """Async platform control-plane client (projects, live_runs, trace_scores)."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = 30.0,
        transport: httpx2.AsyncBaseTransport | None = None,
        api_key: str | None = None,
        project_id: str | None = None,
    ) -> None:
        """``api_key`` defaults to ``opengrade.set_api_key()`` / ``OPENGRADE_API_KEY``."""
        resolved = resolve_api_base_url(base_url)
        self._http = _AsyncHttpTransport(
            resolved, timeout=timeout, transport=transport, api_key=api_key
        )
        self.base_url = resolved
        self._project_id = project_id
        self.projects = _AsyncProjectsResource(self._http, self._project)
        self.live_runs = _AsyncLiveRunsResource(self._http, self._project)
        self.trace_scores = _AsyncTraceScoresResource(self._http, self._project)

    def _project(self, project_id: str | None = None) -> str:
        return resolve_bound_project(project_id, bound=self._project_id)

    async def health(self) -> HealthResponse:
        return await self._http.request_model("GET", "/health", response_model=HealthResponse)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> AsyncClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

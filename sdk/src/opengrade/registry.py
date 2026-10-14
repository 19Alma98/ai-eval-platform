from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx2

from aiobs._http import _HttpTransport
from aiobs.models import AppConfigAliasResponse, AppConfigResponse


class AppConfigClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        self._http = _HttpTransport(base_url, timeout=timeout, transport=transport)
        self._owns_http = True

    @classmethod
    def from_transport(cls, http: _HttpTransport) -> AppConfigClient:
        client = cls.__new__(cls)
        client._http = http
        client._owns_http = False
        return client

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> AppConfigClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
    ) -> Any:
        return self._http.request(method, path, body=body, query=query)

    def create_app_config(
        self,
        project_id: str,
        name: str,
        *,
        prompt: dict[str, Any] | None = None,
        model: dict[str, Any] | None = None,
        retrieval: dict[str, Any] | None = None,
        description: str | None = None,
    ) -> AppConfigResponse:
        body: dict[str, Any] = {"name": name}
        if description is not None:
            body["description"] = description
        if prompt is not None:
            body["prompt"] = prompt
        if model is not None:
            body["model"] = model
        if retrieval is not None:
            body["retrieval"] = retrieval
        return self._http.request_model(
            "POST",
            f"/api/v1/projects/{project_id}/app-configs",
            body=body,
            response_model=AppConfigResponse,
        )

    def list_app_configs(
        self,
        project_id: str,
        *,
        name: str | None = None,
        latest: bool = False,
    ) -> list[AppConfigResponse]:
        query: dict[str, str] = {}
        if name is not None:
            query["name"] = name
        if latest:
            query["latest"] = "true"
        return self._http.request_model_list(
            "GET",
            f"/api/v1/projects/{project_id}/app-configs",
            query=query or None,
            response_model=AppConfigResponse,
        )

    def set_alias(self, project_id: str, alias: str, app_config_id: str) -> AppConfigAliasResponse:
        encoded = quote(alias, safe="")
        return self._http.request_model(
            "PUT",
            f"/api/v1/projects/{project_id}/app-config-aliases/{encoded}",
            body={"app_config_id": app_config_id},
            response_model=AppConfigAliasResponse,
        )

    def get_aliases(self, project_id: str) -> list[AppConfigAliasResponse]:
        return self._http.request_model_list(
            "GET",
            f"/api/v1/projects/{project_id}/app-config-aliases",
            response_model=AppConfigAliasResponse,
        )

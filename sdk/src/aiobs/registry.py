"""HTTP client for app config registry REST endpoints."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


class AppConfigClient:
    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
    ) -> Any:
        url = f"{self._base_url}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        data: bytes | None = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
        if not raw:
            return None
        return json.loads(raw.decode("utf-8"))

    def create_app_config(
        self,
        project_id: str,
        name: str,
        *,
        prompt: dict[str, Any] | None = None,
        model: dict[str, Any] | None = None,
        retrieval: dict[str, Any] | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"name": name}
        if description is not None:
            body["description"] = description
        if prompt is not None:
            body["prompt"] = prompt
        if model is not None:
            body["model"] = model
        if retrieval is not None:
            body["retrieval"] = retrieval
        result = self._request(
            "POST",
            f"/api/v1/projects/{project_id}/app-configs",
            body=body,
        )
        assert isinstance(result, dict)
        return result

    def list_app_configs(
        self,
        project_id: str,
        *,
        name: str | None = None,
        latest: bool = False,
    ) -> list[dict[str, Any]]:
        query: dict[str, str] = {}
        if name is not None:
            query["name"] = name
        if latest:
            query["latest"] = "true"
        result = self._request(
            "GET",
            f"/api/v1/projects/{project_id}/app-configs",
            query=query or None,
        )
        assert isinstance(result, list)
        return result

    def set_alias(self, project_id: str, alias: str, app_config_id: str) -> dict[str, Any]:
        encoded = quote(alias, safe="")
        result = self._request(
            "PUT",
            f"/api/v1/projects/{project_id}/app-config-aliases/{encoded}",
            body={"app_config_id": app_config_id},
        )
        assert isinstance(result, dict)
        return result

    def get_aliases(self, project_id: str) -> list[dict[str, Any]]:
        result = self._request(
            "GET",
            f"/api/v1/projects/{project_id}/app-config-aliases",
        )
        assert isinstance(result, list)
        return result

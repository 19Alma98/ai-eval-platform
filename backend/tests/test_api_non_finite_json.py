from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI, Request
from httpx2 import ASGITransport, AsyncClient
from pydantic import BaseModel, ConfigDict

import test_api_evaluation
from aiobs_server.api.errors import register_exception_handlers
from aiobs_server.api.json_guard import RejectNonFiniteJsonMiddleware

client = test_api_evaluation.client  # shared in-memory app fixture

JSON = {"content-type": "application/json"}


def _body_limited_app(*, max_body_bytes: int) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RejectNonFiniteJsonMiddleware, max_body_bytes=max_body_bytes)

    @app.post("/echo")
    async def echo(request: Request) -> dict[str, int]:
        body = await request.body()
        return {"n": len(body)}

    return app


@pytest.mark.asyncio
@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity", "1e999"])
async def test_non_finite_number_in_any_field_is_422(client: AsyncClient, token: str) -> None:
    project = await client.post("/api/v1/projects", json={"name": "NaN guard"})
    dataset = await client.post(
        f"/api/v1/projects/{project.json()['id']}/datasets", json={"name": "d"}
    )
    dataset_id = dataset.json()["id"]
    # input is Any: pydantic's allow_inf_nan cannot reach it, and a stored NaN
    # would break every later response that serializes the item.
    body = f'{{"input": {{"temperature": {token}}}}}'

    resp = await client.post(f"/api/v1/datasets/{dataset_id}/items", content=body, headers=JSON)

    assert resp.status_code == 422, resp.text
    (error,) = resp.json()["detail"]
    assert error["type"] == "finite_number"
    assert error["input"] == token
    detail = await client.get(f"/api/v1/datasets/{dataset_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["items"] == []


@pytest.mark.asyncio
async def test_non_finite_number_in_json_subtype_is_422(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/projects",
        content='{"name": "p", "x": NaN}',
        headers={"content-type": "application/merge-patch+json; charset=utf-8"},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_finite_and_malformed_bodies_pass_through(client: AsyncClient) -> None:
    ok = await client.post("/api/v1/projects", content='{"name": "fine", "x": 1.5}', headers=JSON)
    assert ok.status_code == 201, ok.text
    # The guard leaves malformed JSON to FastAPI's own json_invalid error.
    bad = await client.post("/api/v1/projects", content='{"name": ', headers=JSON)
    assert bad.status_code == 422
    assert bad.json()["detail"][0]["type"] == "json_invalid"


class _StrictBody(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    x: float


@pytest.mark.asyncio
async def test_validation_error_echoing_nan_is_422_not_500() -> None:
    # Without the edge guard, FastAPI's default handler echoes the NaN input back
    # and fails to serialize it.
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/strict")
    async def strict(body: _StrictBody) -> dict[str, float]:
        return {"x": body.x}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/strict", content='{"x": NaN}', headers=JSON)

    assert resp.status_code == 422, resp.text
    (error,) = resp.json()["detail"]
    assert error["type"] == "finite_number"
    assert error["input"] == "nan"


@pytest.mark.asyncio
async def test_content_length_over_limit_is_413() -> None:
    app = _body_limited_app(max_body_bytes=64)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/echo", content=b"{" + b"x" * 64 + b"}", headers=JSON)

    assert resp.status_code == 413, resp.text
    assert resp.json() == {"detail": "Request body too large"}


@pytest.mark.asyncio
async def test_chunked_body_over_limit_is_413() -> None:
    app = _body_limited_app(max_body_bytes=64)
    payload = b'{"x":"' + b"y" * 80 + b'"}'

    async def chunks() -> AsyncIterator[bytes]:
        for start in range(0, len(payload), 16):
            yield payload[start : start + 16]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/echo", content=chunks(), headers=JSON)

    assert resp.status_code == 413, resp.text
    assert resp.json() == {"detail": "Request body too large"}


@pytest.mark.asyncio
async def test_body_at_limit_reaches_handler() -> None:
    app = _body_limited_app(max_body_bytes=64)
    body = b'{"x":"' + b"z" * 56 + b'"}'  # exactly 64 bytes
    assert len(body) == 64
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/echo", content=body, headers=JSON)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"n": 64}


@pytest.mark.asyncio
async def test_non_finite_still_422_under_size_limit() -> None:
    app = _body_limited_app(max_body_bytes=1024)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/echo", content=b'{"x": NaN}', headers=JSON)

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"][0]["type"] == "finite_number"

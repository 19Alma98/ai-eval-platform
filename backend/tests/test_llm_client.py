from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from aiobs.config import Settings
from aiobs.infrastructure.llm import LiteLlmClient


@pytest.mark.asyncio
async def test_litellm_client_passes_api_base() -> None:
    settings = Settings(
        llm_model="ollama/gemma4:e2b",
        llm_api_base="http://localhost:11434",
        llm_api_key=None,
    )
    client = LiteLlmClient(settings)
    fake_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"score": 1.0}'))]
    )

    with patch(
        "aiobs.infrastructure.llm.litellm.acompletion",
        new_callable=AsyncMock,
        return_value=fake_response,
    ) as mock_complete:
        data = await client.complete(system="sys", user="usr")

    assert data == '{"score": 1.0}'
    kwargs: dict[str, Any] = mock_complete.await_args.kwargs
    assert kwargs["model"] == "ollama/gemma4:e2b"
    assert kwargs["api_base"] == "http://localhost:11434"
    assert "api_key" not in kwargs


def _response(content: str | None) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@pytest.mark.asyncio
async def test_complete_defaults_to_deterministic_settings() -> None:
    client = LiteLlmClient(Settings(llm_model="m", llm_temperature=0.0, llm_seed=42))
    with patch(
        "aiobs.infrastructure.llm.litellm.acompletion",
        new_callable=AsyncMock,
        return_value=_response('{"a": 1}'),
    ) as mock_complete:
        text = await client.complete(system="sys", user="usr")

    assert text == '{"a": 1}'
    kwargs: dict[str, Any] = mock_complete.await_args.kwargs
    assert kwargs["temperature"] == 0.0
    assert kwargs["seed"] == 42
    assert kwargs["drop_params"] is True
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ]


@pytest.mark.asyncio
async def test_complete_overrides_and_history() -> None:
    client = LiteLlmClient(Settings(llm_model="m", llm_seed=None))
    history = [
        {"role": "assistant", "content": "oops"},
        {"role": "user", "content": "fix it"},
    ]
    with patch(
        "aiobs.infrastructure.llm.litellm.acompletion",
        new_callable=AsyncMock,
        return_value=_response("{}"),
    ) as mock_complete:
        await client.complete(
            system="sys", user="usr", model="other", temperature=0.3, history=history
        )

    kwargs: dict[str, Any] = mock_complete.await_args.kwargs
    assert kwargs["model"] == "other"
    assert kwargs["temperature"] == 0.3
    assert "seed" not in kwargs
    assert kwargs["messages"][2:] == history


@pytest.mark.asyncio
async def test_complete_returns_empty_string_for_empty_content() -> None:
    client = LiteLlmClient(Settings(llm_model="m"))
    with patch(
        "aiobs.infrastructure.llm.litellm.acompletion",
        new_callable=AsyncMock,
        return_value=_response(None),
    ):
        assert await client.complete(system="s", user="u") == ""

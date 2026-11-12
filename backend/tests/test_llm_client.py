from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from opengrade_server.config import Settings
from opengrade_server.infrastructure.llm import LiteLlmClient


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
        "opengrade_server.infrastructure.llm.litellm.acompletion",
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
    client = LiteLlmClient(
        Settings(llm_model="m", llm_api_key="test", llm_temperature=0.0, llm_seed=42)
    )
    with patch(
        "opengrade_server.infrastructure.llm.litellm.acompletion",
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
    client = LiteLlmClient(Settings(llm_model="m", llm_api_key="test", llm_seed=None))
    history = [
        {"role": "assistant", "content": "oops"},
        {"role": "user", "content": "fix it"},
    ]
    with patch(
        "opengrade_server.infrastructure.llm.litellm.acompletion",
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
    client = LiteLlmClient(Settings(llm_model="m", llm_api_key="test"))
    with patch(
        "opengrade_server.infrastructure.llm.litellm.acompletion",
        new_callable=AsyncMock,
        return_value=_response(None),
    ):
        assert await client.complete(system="s", user="u") == ""


@pytest.mark.asyncio
async def test_complete_refuses_cloud_model_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opengrade_server.evaluation.judges.errors import (
        JUDGE_NOT_CONFIGURED_MSG,
        JudgeNotConfiguredError,
    )

    for key in (
        "LLM_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    client = LiteLlmClient(
        Settings(llm_model="gemini/gemini-3.8-flash", llm_api_key=None, llm_api_base=None)
    )
    with patch(
        "opengrade_server.infrastructure.llm.litellm.acompletion",
        new_callable=AsyncMock,
    ) as mock_complete:
        with pytest.raises(JudgeNotConfiguredError, match=re.escape(JUDGE_NOT_CONFIGURED_MSG)):
            await client.complete(system="s", user="u")
    mock_complete.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model", "env"),
    [
        ("openai/gpt-4o-mini", {"OPENAI_API_KEY": "sk-test"}),
        ("anthropic/claude-3-5-haiku-latest", {"ANTHROPIC_API_KEY": "sk-ant-test"}),
        (
            "bedrock/anthropic.claude-3-haiku-20240307-v1:0",
            {
                "AWS_ACCESS_KEY_ID": "AKIATEST",
                "AWS_SECRET_ACCESS_KEY": "secret",
            },
        ),
        (
            "vertex_ai/gemini-1.5-flash",
            {"VERTEXAI_PROJECT": "proj", "VERTEXAI_LOCATION": "us-central1"},
        ),
        (
            "azure/gpt-4o",
            {
                "AZURE_API_KEY": "azure-key",
                "AZURE_API_BASE": "https://example.openai.azure.com",
                "AZURE_API_VERSION": "2024-02-01",
            },
        ),
        ("gemini/gemini-3.8-flash", {"GEMINI_API_KEY": "gemini-key"}),
    ],
)
async def test_complete_allows_provider_env_credentials(
    monkeypatch: pytest.MonkeyPatch,
    model: str,
    env: dict[str, str],
) -> None:
    """LiteLLM reads provider env vars; LLM_API_KEY must not be required."""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    client = LiteLlmClient(Settings(llm_model=model, llm_api_key=None, llm_api_base=None))
    with patch(
        "opengrade_server.infrastructure.llm.litellm.acompletion",
        new_callable=AsyncMock,
        return_value=_response('{"ok": true}'),
    ) as mock_complete:
        text = await client.complete(system="s", user="u")

    assert text == '{"ok": true}'
    mock_complete.assert_awaited_once()
    assert "api_key" not in mock_complete.await_args.kwargs

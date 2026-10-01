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
        data = await client.complete_json(system="sys", user="usr")

    assert data == {"score": 1.0}
    kwargs: dict[str, Any] = mock_complete.await_args.kwargs
    assert kwargs["model"] == "ollama/gemma4:e2b"
    assert kwargs["api_base"] == "http://localhost:11434"
    assert "api_key" not in kwargs

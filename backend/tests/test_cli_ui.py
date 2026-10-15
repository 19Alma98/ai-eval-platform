from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from opengrade_server.cli import (
    EXIT_CONFIG,
    PortInUseError,
    app,
    assert_port_available,
    ui_config_warnings,
)
from opengrade_server.config import Settings

runner = CliRunner()


def test_assert_port_available_raises_when_listener_accepts() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        with pytest.raises(PortInUseError) as exc_info:
            assert_port_available("127.0.0.1", port)
        assert exc_info.value.port == port
        assert exc_info.value.host == "127.0.0.1"


def test_assert_port_available_ok_when_nothing_listens() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    assert_port_available("127.0.0.1", port)


def test_ui_exits_when_port_busy() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        with (
            patch("opengrade_server.cli.ui_root", return_value=MagicMock()),
            patch("opengrade_server.cli.uvicorn.run") as run_mock,
        ):
            result = runner.invoke(app, ["ui", "--port", str(port)])
    assert result.exit_code == EXIT_CONFIG
    assert "already in use" in result.stdout
    run_mock.assert_not_called()


def test_ui_config_warnings_missing_gemini_key() -> None:
    settings = Settings(
        llm_model="gemini/gemini-3.8-flash",
        llm_api_key=None,
        llm_api_base=None,
    )
    warnings = ui_config_warnings(settings)
    assert any("LLM_API_KEY" in w for w in warnings)


def test_ui_config_warnings_docker_internal() -> None:
    settings = Settings(
        llm_model="ollama/gemma4:e2b",
        llm_api_key=None,
        llm_api_base="http://host.docker.internal:11434",
    )
    warnings = ui_config_warnings(settings)
    assert any("host.docker.internal" in w for w in warnings)
    assert not any("LLM_API_KEY" in w for w in warnings)


def test_ui_config_warnings_clean_ollama() -> None:
    settings = Settings(
        llm_model="ollama/gemma4:e2b",
        llm_api_key=None,
        llm_api_base="http://localhost:11434",
    )
    assert ui_config_warnings(settings) == []

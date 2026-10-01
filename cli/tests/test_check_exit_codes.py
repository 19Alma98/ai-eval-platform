from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from aiobs_cli.main import (
    EXIT_CONFIG,
    EXIT_GATE_FAILED,
    EXIT_INFRA,
    EXIT_PASS,
    app,
    load_policy_file,
    split_meta,
)
from typer.testing import CliRunner

runner = CliRunner()


def test_load_and_split_meta(tmp_path: Path) -> None:
    path = tmp_path / "aiobs.yaml"
    path.write_text(
        """api_base_url: http://localhost:8000
project_id: 11111111-1111-1111-1111-111111111111
experiment_id: 22222222-2222-2222-2222-222222222222
quality:
  min: 0.85
""",
        encoding="utf-8",
    )
    raw = load_policy_file(path)
    meta, policy = split_meta(raw)
    assert meta["api_base_url"] == "http://localhost:8000"
    assert policy == {"quality": {"min": 0.85}}


def _policy_file(tmp_path: Path) -> Path:
    path = tmp_path / "aiobs.yaml"
    path.write_text(
        """api_base_url: http://localhost:8000
project_id: 11111111-1111-1111-1111-111111111111
experiment_id: 22222222-2222-2222-2222-222222222222
quality:
  min: 0.85
""",
        encoding="utf-8",
    )
    return path


def _mock_response(
    status_code: int, json_body: dict[str, Any] | None = None
) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = "error"
    response.json.return_value = json_body or {}
    return response


def test_check_exit_pass(tmp_path: Path) -> None:
    path = _policy_file(tmp_path)
    with patch("aiobs_cli.main.httpx.post") as post:
        post.return_value = _mock_response(
            200,
            {
                "status": "passed",
                "checks": [
                    {
                        "metric": "quality.min",
                        "actual": 0.9,
                        "threshold": 0.85,
                        "status": "passed",
                    }
                ],
            },
        )
        result = runner.invoke(app, ["check", "--policy", str(path)])
    assert result.exit_code == EXIT_PASS


def test_check_exit_gate_failed(tmp_path: Path) -> None:
    path = _policy_file(tmp_path)
    with patch("aiobs_cli.main.httpx.post") as post:
        post.return_value = _mock_response(
            200,
            {
                "status": "failed",
                "checks": [
                    {
                        "metric": "quality.min",
                        "actual": 0.1,
                        "threshold": 0.85,
                        "status": "failed",
                    }
                ],
            },
        )
        result = runner.invoke(app, ["check", "--policy", str(path)])
    assert result.exit_code == EXIT_GATE_FAILED


def test_check_exit_config_on_400(tmp_path: Path) -> None:
    path = _policy_file(tmp_path)
    with patch("aiobs_cli.main.httpx.post") as post:
        post.return_value = _mock_response(400)
        result = runner.invoke(app, ["check", "--policy", str(path)])
    assert result.exit_code == EXIT_CONFIG


def test_check_exit_infra_on_network_error(tmp_path: Path) -> None:
    import httpx

    path = _policy_file(tmp_path)
    with patch("aiobs_cli.main.httpx.post") as post:
        post.side_effect = httpx.ConnectError("down")
        result = runner.invoke(app, ["check", "--policy", str(path)])
    assert result.exit_code == EXIT_INFRA


def test_check_exit_config_missing_ids(tmp_path: Path) -> None:
    path = tmp_path / "aiobs.yaml"
    path.write_text("quality:\n  min: 0.85\n", encoding="utf-8")
    result = runner.invoke(app, ["check", "--policy", str(path)])
    assert result.exit_code == EXIT_CONFIG

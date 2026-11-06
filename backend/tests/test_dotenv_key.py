"""Upsert / remove a single key in a ``.env`` file."""

from __future__ import annotations

from pathlib import Path

import pytest

from opengrade_server.infrastructure.dotenv_key import remove_env_key, upsert_env_key


def test_upsert_creates_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    path = upsert_env_key("LLM_API_KEY", "secret-one")
    assert path.read_text(encoding="utf-8") == "LLM_API_KEY=secret-one\n"


def test_upsert_replaces_existing_preserves_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    env = tmp_path / ".env"
    env.write_text(
        "# comment\nLLM_MODEL=gemini/x\nLLM_API_KEY=old\nFOO=bar\n",
        encoding="utf-8",
    )
    upsert_env_key("LLM_API_KEY", "new-key")
    text = env.read_text(encoding="utf-8")
    assert "LLM_MODEL=gemini/x" in text
    assert "FOO=bar" in text
    assert "# comment" in text
    assert "LLM_API_KEY=new-key" in text
    assert "old" not in text


def test_upsert_quotes_values_with_spaces(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    upsert_env_key("LLM_API_KEY", "a b")
    assert (tmp_path / ".env").read_text(encoding="utf-8") == 'LLM_API_KEY="a b"\n'


def test_remove_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    env = tmp_path / ".env"
    env.write_text("LLM_API_KEY=x\nLLM_MODEL=m\n", encoding="utf-8")
    remove_env_key("LLM_API_KEY")
    assert env.read_text(encoding="utf-8") == "LLM_MODEL=m\n"


def test_remove_missing_file_is_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert remove_env_key("LLM_API_KEY") is None

from __future__ import annotations

import types

import pytest

from opengrade import cli


def test_main_without_server_prints_install_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "find_spec", lambda name: None)

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert 'pip install "opengrade-ai[ui]"' in capsys.readouterr().err


def test_main_with_server_delegates_to_server_app(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    fake_cli = types.SimpleNamespace(app=lambda: calls.append("app"))
    monkeypatch.setattr(cli, "find_spec", lambda name: object())
    monkeypatch.setattr(cli, "import_module", lambda name: fake_cli)

    cli.main()

    assert calls == ["app"]


def test_main_does_not_mask_broken_server_import(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(name: str) -> None:
        raise ImportError("No module named 'litellm'")

    monkeypatch.setattr(cli, "find_spec", lambda name: object())
    monkeypatch.setattr(cli, "import_module", broken)

    with pytest.raises(ImportError, match="litellm"):
        cli.main()

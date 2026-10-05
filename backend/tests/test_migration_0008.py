from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


def _load_revision():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0008_metrics_packs.py"
    spec = importlib.util.spec_from_file_location("rev_0008_metrics_packs", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_skips_create_when_metrics_packs_exists(monkeypatch) -> None:
    module = _load_revision()
    created: list[object] = []
    monkeypatch.setattr(module.op, "get_bind", lambda: object())
    monkeypatch.setattr(
        module.sa,
        "inspect",
        lambda _bind: SimpleNamespace(has_table=lambda name: name == "metrics_packs"),
    )
    monkeypatch.setattr(module.op, "create_table", lambda *args, **kwargs: created.append(args))

    module.upgrade()

    assert created == []


def test_upgrade_creates_table_when_missing(monkeypatch) -> None:
    module = _load_revision()
    created: list[object] = []
    monkeypatch.setattr(module.op, "get_bind", lambda: object())
    monkeypatch.setattr(
        module.sa,
        "inspect",
        lambda _bind: SimpleNamespace(has_table=lambda _name: False),
    )
    monkeypatch.setattr(module.op, "create_table", lambda *args, **kwargs: created.append(args[0]))

    module.upgrade()

    assert created == ["metrics_packs"]

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4


def _load_revision():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0009_metrics_sets.py"
    spec = importlib.util.spec_from_file_location("rev_0009_metrics_sets", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_entry_is_default_from_not_removable() -> None:
    module = _load_revision()
    assert module.entry_is_default({"kind": "hit_at_k", "removable": False}) is True
    assert module.entry_is_default({"kind": "custom", "removable": True}) is False
    assert module.entry_is_default({"kind": "custom"}) is False


def test_upgrade_creates_tables_when_missing(monkeypatch) -> None:
    module = _load_revision()
    created: list[str] = []
    monkeypatch.setattr(module.op, "get_bind", lambda: object())
    monkeypatch.setattr(
        module.sa,
        "inspect",
        lambda _bind: SimpleNamespace(has_table=lambda name: name == "metrics_packs"),
    )
    monkeypatch.setattr(module.op, "create_table", lambda *args, **kwargs: created.append(args[0]))
    monkeypatch.setattr(module.op, "create_index", lambda *args, **kwargs: None)
    monkeypatch.setattr(module.op, "add_column", lambda *args, **kwargs: None)
    monkeypatch.setattr(module.op, "create_foreign_key", lambda *args, **kwargs: None)
    monkeypatch.setattr(module.op, "drop_table", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "backfill_metrics_sets", lambda _conn: None)

    module.upgrade()

    assert "metrics_sets" in created
    assert "metrics_set_entries" in created


def test_backfill_inserts_default_v1_and_skips_missing_pack() -> None:
    module = _load_revision()
    pack_id = uuid4()
    project_id = uuid4()
    eval_id = uuid4()
    inserted_sets: list[dict] = []
    inserted_entries: list[dict] = []

    class FakeConn:
        def execute(self, statement, params=None):  # noqa: ANN001
            sql = str(statement)
            if "FROM metrics_packs" in sql:
                return SimpleNamespace(
                    mappings=lambda: SimpleNamespace(
                        all=lambda: [
                            {
                                "id": pack_id,
                                "project_id": project_id,
                                "entries": [
                                    {
                                        "kind": "hit_at_k",
                                        "enabled": True,
                                        "threshold": 0.8,
                                        "config": {"k": 5},
                                        "evaluator_id": str(eval_id),
                                        "removable": False,
                                    },
                                    {
                                        "kind": "custom",
                                        "enabled": False,
                                        "threshold": None,
                                        "config": {},
                                        "evaluator_id": None,
                                    },
                                ],
                            }
                        ]
                    )
                )
            if "INSERT INTO metrics_sets" in sql:
                inserted_sets.append(params)
                return SimpleNamespace()
            if "INSERT INTO metrics_set_entries" in sql:
                inserted_entries.append(params)
                return SimpleNamespace()
            raise AssertionError(sql)

    module.backfill_metrics_sets(FakeConn())
    assert len(inserted_sets) == 1
    assert inserted_sets[0]["name"] == "Default"
    assert inserted_sets[0]["version"] == 1
    assert inserted_sets[0]["is_project_default"] is True
    assert inserted_sets[0]["project_id"] == project_id
    assert {row["kind"] for row in inserted_entries} == {"hit_at_k", "custom"}
    hit = next(r for r in inserted_entries if r["kind"] == "hit_at_k")
    custom = next(r for r in inserted_entries if r["kind"] == "custom")
    assert hit["is_default"] is True
    assert UUID(str(hit["evaluator_id"])) == eval_id
    assert custom["is_default"] is False

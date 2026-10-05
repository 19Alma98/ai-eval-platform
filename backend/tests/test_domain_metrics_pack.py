from __future__ import annotations

import uuid

import pytest

from aiobs.domain.metrics_pack import (
    DEFAULT_RAG_ENTRIES,
    MetricsPack,
    MetricsPackEntry,
)


def test_create_uses_default_rag_entries() -> None:
    project_id = uuid.uuid4()
    pack = MetricsPack.create(project_id)
    assert pack.project_id == project_id
    assert len(pack.entries) == len(DEFAULT_RAG_ENTRIES)
    assert [e.kind for e in pack.entries] == [e.kind for e in DEFAULT_RAG_ENTRIES]
    assert pack.entries[0].kind == "hit_at_k"
    assert pack.entries[0].config == {"k": 5}
    assert pack.entries[0].removable is False


def test_patch_entry_can_disable_non_removable() -> None:
    pack = MetricsPack.create(uuid.uuid4())
    updated = pack.patch_entry("hit_at_k", enabled=False)
    hit = next(e for e in updated.entries if e.kind == "hit_at_k")
    assert hit.enabled is False
    assert hit.removable is False


def test_patch_entry_updates_threshold_and_merges_config() -> None:
    pack = MetricsPack.create(uuid.uuid4())
    updated = pack.patch_entry("hit_at_k", threshold=0.9, config={"k": 10})
    hit = next(e for e in updated.entries if e.kind == "hit_at_k")
    assert hit.threshold == 0.9
    assert hit.config == {"k": 10}

    latency = next(e for e in updated.entries if e.kind == "latency")
    cleared = updated.patch_entry("latency", threshold=None)
    lat = next(e for e in cleared.entries if e.kind == "latency")
    assert lat.threshold is None


def test_patch_unknown_kind_raises() -> None:
    pack = MetricsPack.create(uuid.uuid4())
    with pytest.raises(ValueError, match="unknown"):
        pack.patch_entry("missing", enabled=False)


def test_cannot_remove_non_removable_entry() -> None:
    pack = MetricsPack.create(uuid.uuid4())
    with pytest.raises(ValueError, match="removable"):
        pack.remove_entry("hit_at_k")


def test_remove_removable_custom_entry() -> None:
    pack = MetricsPack.create(uuid.uuid4())
    custom = MetricsPackEntry(
        kind="custom_judge",
        enabled=True,
        threshold=0.5,
        config={},
        evaluator_id=uuid.uuid4(),
        removable=True,
    )
    with_custom = pack.append_entry(custom)
    assert len(with_custom.entries) == len(DEFAULT_RAG_ENTRIES) + 1

    trimmed = with_custom.remove_entry("custom_judge")
    assert len(trimmed.entries) == len(DEFAULT_RAG_ENTRIES)
    assert all(e.kind != "custom_judge" for e in trimmed.entries)


def test_append_custom_requires_removable_true() -> None:
    pack = MetricsPack.create(uuid.uuid4())
    bad = MetricsPackEntry(
        kind="extra",
        enabled=True,
        threshold=None,
        config={},
        evaluator_id=None,
        removable=False,
    )
    with pytest.raises(ValueError, match="removable"):
        pack.append_entry(bad)


def test_append_rejects_duplicate_kind() -> None:
    pack = MetricsPack.create(uuid.uuid4())
    dup = MetricsPackEntry(
        kind="hit_at_k",
        enabled=True,
        threshold=0.5,
        config={},
        evaluator_id=None,
        removable=True,
    )
    with pytest.raises(ValueError, match="already"):
        pack.append_entry(dup)

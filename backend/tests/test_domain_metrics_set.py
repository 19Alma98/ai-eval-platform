from __future__ import annotations

import uuid

import pytest

from aiobs.domain.metrics_set import (
    DEFAULT_RAG_SET_ENTRIES,
    MetricsSet,
    MetricsSetEntry,
)


def test_create_project_default_seeds_is_default_rows() -> None:
    project_id = uuid.uuid4()
    s = MetricsSet.create_project_default(project_id)
    assert s.project_id == project_id
    assert s.name == "Default"
    assert s.version == 1
    assert s.is_project_default is True
    assert [e.kind for e in s.entries] == [e.kind for e in DEFAULT_RAG_SET_ENTRIES]
    assert all(e.is_default for e in s.entries)


def test_default_rag_set_includes_ragas_core_and_answer_relevance() -> None:
    kinds = [e.kind for e in DEFAULT_RAG_SET_ENTRIES]
    assert kinds == [
        "hit_at_k",
        "recall_at_k",
        "mrr",
        "context_precision",
        "context_recall",
        "must_contain",
        "groundedness",
        "answer_relevance",
        "correctness",
        "latency",
    ]
    by_kind = {e.kind: e for e in DEFAULT_RAG_SET_ENTRIES}
    assert by_kind["context_recall"].threshold == 0.7
    assert by_kind["answer_relevance"].threshold == 0.7
    assert by_kind["context_recall"].enabled is True


def test_create_custom_never_sets_project_default() -> None:
    entry = MetricsSetEntry(
        id=uuid.uuid4(),
        kind="hit_at_k",
        enabled=True,
        threshold=0.8,
        config={"k": 5},
        evaluator_id=None,
        is_default=True,
    )
    s = MetricsSet.create(uuid.uuid4(), "RAG-strict", entries=(entry,))
    assert s.is_project_default is False
    assert s.version == 1
    assert s.entries[0].is_default is False


def test_cannot_remove_is_default_entry() -> None:
    s = MetricsSet.create_project_default(uuid.uuid4())
    with pytest.raises(ValueError, match="is_default"):
        s.remove_entry("hit_at_k")


def test_can_disable_is_default_entry() -> None:
    s = MetricsSet.create_project_default(uuid.uuid4())
    updated = s.patch_entry("hit_at_k", enabled=False)
    hit = next(e for e in updated.entries if e.kind == "hit_at_k")
    assert hit.enabled is False
    assert hit.is_default is True


def test_copy_as_next_version_clears_project_default_and_is_default() -> None:
    s = MetricsSet.create_project_default(uuid.uuid4())
    v2 = s.copy_as_next_version(next_version=2)
    assert v2.id != s.id
    assert v2.name == "Default"
    assert v2.version == 2
    assert v2.is_project_default is False
    assert v2.project_id == s.project_id
    assert [e.kind for e in v2.entries] == [e.kind for e in s.entries]
    assert all(not e.is_default for e in v2.entries)
    assert {e.id for e in v2.entries}.isdisjoint({e.id for e in s.entries})


def test_append_rejects_duplicate_kind() -> None:
    s = MetricsSet.create_project_default(uuid.uuid4())
    dup = MetricsSetEntry(
        id=uuid.uuid4(),
        kind="hit_at_k",
        enabled=True,
        threshold=0.5,
        config={},
        evaluator_id=None,
        is_default=False,
    )
    with pytest.raises(ValueError, match="already"):
        s.append_entry(dup)


def test_create_rejects_empty_name_and_version_below_one() -> None:
    pid = uuid.uuid4()
    with pytest.raises(ValueError, match="name"):
        MetricsSet.create(pid, "  ")
    with pytest.raises(ValueError, match="version"):
        MetricsSet.create(pid, "X", version=0)

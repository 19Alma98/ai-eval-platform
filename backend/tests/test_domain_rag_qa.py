from __future__ import annotations

import pytest

from opengrade_server.domain.rag_qa import normalize_expected_doc_ids, validate_rag_qa_item


def test_normalize_pipe_and_list() -> None:
    assert normalize_expected_doc_ids("a|b") == ["a", "b"]
    assert normalize_expected_doc_ids(["x", "y"]) == ["x", "y"]


def test_validate_ok() -> None:
    meta = validate_rag_qa_item(
        input="What is PTO?",
        expected_output="20 days",
        metadata={"expected_doc_ids": ["pto-1"]},
    )
    assert meta.expected_doc_ids == ["pto-1"]


def test_validate_normalizes_must_contain() -> None:
    meta = validate_rag_qa_item(
        input="What is PTO?",
        expected_output="20 days",
        metadata={"expected_doc_ids": ["pto-1"], "must_contain": "20 days|PTO"},
    )
    assert meta.must_contain == ["20 days", "PTO"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"input": "", "expected_output": "a", "metadata": {"expected_doc_ids": ["d"]}},
        {"input": "q", "expected_output": None, "metadata": {"expected_doc_ids": ["d"]}},
        {"input": "q", "expected_output": "a", "metadata": {"expected_doc_ids": []}},
        {"input": "q", "expected_output": "a", "metadata": {}},
    ],
)
def test_validate_rejects(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        validate_rag_qa_item(**kwargs)


def test_must_contain_keeps_commas_inside_phrases() -> None:
    meta = validate_rag_qa_item(
        input="q",
        expected_output="a",
        metadata={"expected_doc_ids": "a,b", "must_contain": "$1,000|10:00-16:00, local time"},
    )
    assert meta.expected_doc_ids == ["a", "b"]
    assert meta.must_contain == ["$1,000", "10:00-16:00, local time"]


@pytest.mark.parametrize(
    "label",
    [{"answerable": False}, {"answerable": "false"}, {"expected_refusal": True}],
)
def test_unanswerable_item_needs_no_gold_docs_nor_reference(label: dict) -> None:
    meta = validate_rag_qa_item(input="Who is the CEO?", expected_output=None, metadata=label)
    assert meta.expected_doc_ids is None
    assert meta.answerable is False


def test_unanswerable_item_drops_empty_gold_docs_and_keeps_given_ones() -> None:
    empty = validate_rag_qa_item(
        input="q",
        expected_output="Not in the docs.",
        metadata={"answerable": False, "expected_doc_ids": []},
    )
    assert empty.expected_doc_ids is None
    given = validate_rag_qa_item(
        input="q",
        expected_output=None,
        metadata={"answerable": False, "expected_doc_ids": "faq|pricing"},
    )
    assert given.expected_doc_ids == ["faq", "pricing"]


@pytest.mark.parametrize(
    "metadata",
    [{"answerable": True}, {"answerable": "maybe"}, {"expected_refusal": False}],
)
def test_answerable_or_unlabelled_items_still_need_gold_docs(metadata: dict) -> None:
    with pytest.raises(ValueError, match="expected_doc_ids"):
        validate_rag_qa_item(input="q", expected_output="a", metadata=metadata)


def test_unanswerable_item_rejects_blank_reference() -> None:
    with pytest.raises(ValueError, match="expected_output"):
        validate_rag_qa_item(input="q", expected_output="  ", metadata={"answerable": False})

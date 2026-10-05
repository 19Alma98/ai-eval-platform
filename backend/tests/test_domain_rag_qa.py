from __future__ import annotations

import pytest

from aiobs.domain.rag_qa import normalize_expected_doc_ids, validate_rag_qa_item


def test_normalize_pipe_and_list() -> None:
    assert normalize_expected_doc_ids("a|b") == ["a", "b"]
    assert normalize_expected_doc_ids(["x", "y"]) == ["x", "y"]


def test_validate_ok() -> None:
    meta = validate_rag_qa_item(
        input="What is PTO?",
        expected_output="20 days",
        metadata={"expected_doc_ids": ["pto-1"]},
    )
    assert meta["expected_doc_ids"] == ["pto-1"]


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

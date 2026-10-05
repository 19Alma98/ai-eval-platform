from __future__ import annotations

import pytest

from aiobs.application.dataset_import import parse_import_payload, row_to_item_fields


def test_parse_csv_requires_headers() -> None:
    raw = b"question,expected_answer\nQ?,A\n"
    with pytest.raises(ValueError, match="expected_doc_ids"):
        parse_import_payload(filename="x.csv", raw=raw)


def test_row_to_item_fields_json_array_string_doc_ids() -> None:
    _, _, meta = row_to_item_fields(
        {
            "question": "Q?",
            "expected_answer": "A",
            "expected_doc_ids": '["a", "b"]',
        }
    )
    assert meta["expected_doc_ids"] == ["a", "b"]


def test_row_to_item_fields_must_contain_pipe() -> None:
    _, _, meta = row_to_item_fields(
        {
            "question": "Q?",
            "expected_answer": "A",
            "expected_doc_ids": "pto",
            "must_contain": "20 days|PTO",
        }
    )
    assert meta["must_contain"] == ["20 days", "PTO"]


def test_row_to_item_fields_empty_must_contain_omitted() -> None:
    _, _, meta = row_to_item_fields(
        {
            "question": "Q?",
            "expected_answer": "A",
            "expected_doc_ids": "pto",
            "must_contain": "",
        }
    )
    assert "must_contain" not in meta

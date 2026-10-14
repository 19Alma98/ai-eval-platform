from __future__ import annotations

import pytest

from aiobs_server.application.dataset_import import parse_import_payload, row_to_item_fields


def test_parse_csv_requires_headers() -> None:
    raw = b"question,expected_answer\nQ?,A\n"
    with pytest.raises(ValueError, match="expected_doc_ids"):
        parse_import_payload(filename="x.csv", raw=raw)


def test_parse_csv_accepts_sdk_column_aliases() -> None:
    raw = b"input,expected_output,expected_doc_ids\nQ?,A,a\n"
    parsed = parse_import_payload(filename="x.csv", raw=raw)
    assert len(parsed.rows) == 1
    question, answer, meta = row_to_item_fields(parsed.rows[0])
    assert question == "Q?"
    assert answer == "A"
    assert meta["expected_doc_ids"] == ["a"]


def test_parse_jsonl() -> None:
    raw = (
        b'{"question": "Q?", "expected_answer": "A", "expected_doc_ids": ["a"]}\n'
        b'{"input": "Q2?", "expected_output": "A2", "expected_doc_ids": ["b"]}\n'
    )
    parsed = parse_import_payload(filename="x.jsonl", raw=raw)
    assert len(parsed.rows) == 2
    q1, a1, _ = row_to_item_fields(parsed.rows[0])
    q2, a2, _ = row_to_item_fields(parsed.rows[1])
    assert (q1, a1) == ("Q?", "A")
    assert (q2, a2) == ("Q2?", "A2")


def test_row_to_item_fields_prefers_input_over_question() -> None:
    question, answer, _ = row_to_item_fields(
        {
            "input": "canonical",
            "question": "alias",
            "expected_output": "out",
            "expected_answer": "alias_out",
            "expected_doc_ids": "pto",
        }
    )
    assert question == "canonical"
    assert answer == "out"


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

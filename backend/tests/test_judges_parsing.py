from __future__ import annotations

import pytest

from aiobs.evaluation.judges.parsing import extract_json_object


def test_plain_json() -> None:
    assert extract_json_object('{"level": 4}') == {"level": 4}


def test_code_fence() -> None:
    text = 'Here you go:\n```json\n{"claims": ["a"]}\n```\nThanks'
    assert extract_json_object(text) == {"claims": ["a"]}


def test_object_wrapped_in_prose() -> None:
    text = 'Sure! {"level": 3, "reasoning": "partial"} Hope this helps.'
    assert extract_json_object(text) == {"level": 3, "reasoning": "partial"}


def test_braces_inside_strings_do_not_break_matching() -> None:
    text = 'Answer: {"reasoning": "uses {curly} and \\"quotes\\"", "level": 5} done'
    assert extract_json_object(text)["level"] == 5


def test_skips_invalid_candidate_and_finds_next_object() -> None:
    text = '{not json} then {"level": 2}'
    assert extract_json_object(text) == {"level": 2}


@pytest.mark.parametrize("text", ["", "   ", "no json here", "[1, 2]", '"just a string"'])
def test_rejects_non_objects(text: str) -> None:
    with pytest.raises(ValueError):
        extract_json_object(text)


def test_invalid_fence_falls_back_to_object_outside_it() -> None:
    text = '```\nuse {x} here\n```\n{"level": 2}'
    assert extract_json_object(text) == {"level": 2}


def test_bare_fence_without_json_tag() -> None:
    text = 'Result:\n```\n{"level": 1}\n```'
    assert extract_json_object(text) == {"level": 1}

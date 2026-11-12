from __future__ import annotations

from opengrade_server.evaluation.judges import prompts


def test_optional_history_text_none_for_string_question() -> None:
    assert prompts.optional_history_text("How many PTO days?") is None


def test_optional_history_text_none_for_empty_history() -> None:
    assert prompts.optional_history_text({"history": [], "question": "Price?"}) is None


def test_optional_history_text_renders_prior_turns() -> None:
    text = prompts.optional_history_text(
        {
            "history": [
                {"role": "user", "content": "Do you have a Pro plan?"},
                {"role": "assistant", "content": "Yes, Pro is available."},
            ],
            "question": "How much does it cost?",
        }
    )
    assert text is not None
    assert "Do you have a Pro plan?" in text
    assert "Yes, Pro is available." in text
    assert "How much does it cost?" not in text  # question is not part of history

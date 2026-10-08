from __future__ import annotations

import uuid

from aiobs.application.live_judge_calibration import aggregate_calibration
from aiobs.domain.live_interaction import LiveInteractionScore, LiveScoreReview


def _score(
    *,
    kind: str,
    label: str,
    model: str = "gpt-test",
    method: str = "claims",
) -> LiveInteractionScore:
    return LiveInteractionScore.create(
        uuid.uuid4(),
        kind,
        label=label,
        score=0.9,
        explanation="judge text",
        metadata={"model": model, "method": method, "prompt_version": "v1"},
    )


def _review(
    score_id: uuid.UUID,
    verdict: str,
    *,
    corrected: str | None = None,
) -> LiveScoreReview:
    return LiveScoreReview.create(
        score_id,
        verdict,
        corrected_explanation=corrected,
    )


def test_aggregate_calibration_groups_and_rates() -> None:
    s1 = _score(kind="groundedness", label="PASS", model="m1")
    s2 = _score(kind="groundedness", label="FAIL", model="m1")
    s3 = _score(kind="answer_relevance", label="PASS", model="m2")
    s_err = _score(kind="groundedness", label="ERROR", model="m1")

    buckets = aggregate_calibration(
        [
            (s1, _review(s1.id, "agree", corrected="better")),
            (s2, _review(s2.id, "disagree")),
            (s3, _review(s3.id, "agree")),
            (s_err, _review(s_err.id, "agree")),
        ]
    )

    by_key = {(b.kind, b.model): b for b in buckets}
    g = by_key[("groundedness", "m1")]
    assert g.n_reviewed == 2
    assert g.n_agree == 1
    assert g.n_disagree == 1
    assert g.agreement_rate == 0.5
    assert g.n_explanation_edits == 1
    assert g.explanation_edit_rate == 0.5

    ar = by_key[("answer_relevance", "m2")]
    assert ar.n_reviewed == 1
    assert ar.agreement_rate == 1.0
    assert len(buckets) == 2  # ERROR score excluded


def test_live_score_review_domain_validation() -> None:
    review = LiveScoreReview.create(uuid.uuid4(), "Agree", note="  ok  ")
    assert review.verdict == "agree"
    assert review.note == "ok"

    try:
        LiveScoreReview.create(uuid.uuid4(), "maybe")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "verdict" in str(exc)

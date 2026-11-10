"""04 - Monitor your applications in production with your own metrics.

Use case: "I want to monitor my applications live, with metrics made for my product."

In production there is no gold answer: you cannot compute "correctness" against a
reference. You can still measure plenty, continuously, on real traffic:

  - your Python metrics, run automatically on (a sample of) the calls: here the same
    ``cites_retrieved_source`` used in the tests of script 02, plus production-only ones;
  - values your code already knows (a hand-off to a human, a fallback, a cache hit):
    ``og.log_score``;
  - what users think: thumbs up / down with ``og.log_feedback``;
  - optionally, an LLM judge described in plain words (``opengrade.LlmJudge``);
  - and alert rules on all of the above, defined as code.

What this script shows, step by step:

  1. Turn on production mode: environment, version, live interactions.
  2. Attach metrics to the production entry point (``@opengrade.trace(metrics=...)``).
  3. Simulate real traffic (users, conversations), log business scores and feedback.
  4. Find the bad answers programmatically (the Live "Failing" list).
  5. Create alert rules as code (idempotent: safe to run at every deploy).

Run:  uv run python 04_custom_metrics_and_monitoring.py
Then: UI -> Production -> Health / Live / Alerts.
"""

from __future__ import annotations

import sys
import time
from typing import Any

import opengrade
from opengrade import Opengrade, Settings, current

from nimbus_apps import settings
from nimbus_apps.console import note, step, title
from nimbus_apps.quality import answer_is_concise, cites_retrieved_source, is_refusal
from nimbus_apps.rag import answer_question

# ---------------------------------------------------------------------------------------
# Production-only metrics: no expected answer needed, only what the call itself produced.
# ---------------------------------------------------------------------------------------


@opengrade.metric(threshold=0.5, version=1, requires=("documents",))
def retrieval_confidence(s: opengrade.Sample) -> opengrade.Score:
    """How sure the retriever was: top BM25 score scaled to 0-1 (8 or more = 1).

    Low values mean the retriever was guessing: the question is probably not covered by
    the knowledge base, or phrased in words the documents do not use.
    """
    top = max(float(d.get("score") or 0.0) for d in s.documents)
    return opengrade.Score(min(top / 8.0, 1.0), explanation=f"top retrieval score {top:.1f}")


# Two from nimbus_apps/quality.py (also used in the tests of script 02) + one defined here.
PRODUCTION_METRICS = [cites_retrieved_source, answer_is_concise, retrieval_confidence]


# ---------------------------------------------------------------------------------------
# Production code: the assistant, and the web handler that calls it.
# ---------------------------------------------------------------------------------------


@opengrade.trace(
    name="assistant",
    metrics=PRODUCTION_METRICS,  # run after each call, in a background thread
    metrics_sample_rate=1.0,  # score 100% of the calls (use e.g. 0.1 on heavy traffic)
)
def assistant(question: str) -> str:
    """The metrics see this function's input, its return value (the answer) and the
    documents recorded inside it by set_retrieval_documents."""
    return answer_question(question)


@opengrade.trace(name="support_chat")
def support_chat(question: str, *, user_id: str, conversation_id: str) -> dict[str, Any]:
    """Your HTTP handler: one call per chat message (the outermost span = the live
    interaction)."""
    opengrade.set_user(user_id)
    opengrade.set_session(conversation_id)
    opengrade.set_input(question)  # what the live view shows as the question

    answer = assistant(question)

    # A value your code knows already, logged as a score on the current trace. Here a
    # business KPI: did the assistant solve it, or did we hand it over to a human agent?
    # Without a threshold, 0 (False) is FAIL and anything else is PASS.
    handed_over = is_refusal(answer)
    if handed_over:
        answer += " I have opened a ticket: a colleague will reply by e-mail."
    current().log_score(
        "resolved_by_assistant",
        not handed_over,
        explanation="no answer in the docs: ticket opened" if handed_over else "answered",
    )
    opengrade.set_output(answer)  # what the live view shows as the answer
    # The trace id goes back to the frontend with the answer: the thumbs up/down
    # buttons send it back, to attach the feedback to this trace.
    return {"answer": answer, "trace_id": opengrade.current_trace_id()}


# Simulated traffic: (user, conversation, question). Some questions are not covered by
# the docs, one is a known weak spot of the assistant ("without internet").
TRAFFIC = [
    ("u-01", "c-01", "How much does the Pro plan cost?"),
    ("u-01", "c-01", "Can I get a refund on my annual subscription?"),
    ("u-02", "c-02", "When do sharing links expire?"),
    ("u-02", "c-02", "Can I put a password on a sharing link?"),
    ("u-03", "c-03", "Who is the CEO of Nimbus?"),
    ("u-04", "c-04", "How do I enable two-factor authentication?"),
    ("u-04", "c-04", "How long is the password reset link valid?"),
    ("u-05", "c-05", "Can I pay with PayPal?"),
    ("u-06", "c-06", "Can I work on my folders without internet?"),
    ("u-06", "c-06", "What HTTP status do I get when I exceed the API rate limit?"),
    ("u-07", "c-07", "How much storage do I get on the Free plan?"),
    ("u-08", "c-08", "Does Nimbus have an app for smartwatches?"),
    ("u-09", "c-09", "For how long is version history kept on Business accounts?"),
    ("u-10", "c-10", "Which plan do I need for single sign-on with Okta?"),
]


def ensure_alert(client: Any, existing: dict[str, Any], **rule: Any) -> None:
    """Create the rule unless one with the same name exists (safe to re-run)."""
    if rule["name"] in existing:
        print(f"  = {rule['name']} (exists, state={existing[rule['name']].state})")
        return
    created = client.alerts.create(**rule)
    print(f"  + {created.name}: {created.metric} {rule.get('score_name') or ''}".rstrip())


def main() -> None:
    title("OpenGrade SDK tour - 04 Custom metrics and production monitoring")

    og = Opengrade(Settings(tracking_uri=settings.TRACKING_URI, project_slug=settings.PROJECT))
    with og.activate():
        if og.set_project(settings.PROJECT) is None:
            sys.exit(f"OpenGrade is not reachable at {settings.TRACKING_URI}: start it first.")

        step(1, "Production mode")
        og.init_tracing(
            service_name="nimbus-support",
            instrument="auto",
            environment="prod",  # Production -> Health can be filtered per environment...
            version=settings.APP_VERSION,  # ...and compared per release ("By version" table)
            live=True,  # each outermost traced call becomes a "live interaction"
            # Share of the live interactions graded by the platform's LLM judges
            # (groundedness, answer relevance...). 0 = no judge calls, e.g. no judge model.
            live_sample_rate=1.0 if settings.USE_LLM_JUDGES else 0.0,
        )
        note(
            """live=True: every support_chat call is listed in Production -> Live with its
            question, answer, documents and all the scores attached to it."""
        )

        if settings.USE_LLM_JUDGES:
            # A judge described in plain words; live=True scores production traffic too.
            tone = opengrade.LlmJudge(
                "support_tone",
                criteria="The answer is polite, clear, and does not blame the customer.",
                scale="binary",
                live=True,
            )
            tone.register()  # once, e.g. at startup
            print("  LLM judge 'support_tone' registered for live traffic")

        step(2, "Metrics attached to the entry point")
        for metric in PRODUCTION_METRICS:
            summary = (metric.fn.__doc__ or "").strip().splitlines()[0]
            print(f"  - {metric.name:<24} threshold={metric.threshold}  {summary}")
        note(
            """Look at @opengrade.trace(metrics=...) above assistant(). The metrics run after
            the call returns, off the request path: a slow or failing metric never slows down
            or breaks the user's request."""
        )

        step(3, "Simulated traffic + business scores + user feedback")
        for index, (user_id, conversation_id, question) in enumerate(TRAFFIC):
            result = support_chat(question, user_id=user_id, conversation_id=conversation_id)
            refused = "opened a ticket" in result["answer"]
            print(f"  [{user_id}] {question}\n        -> {result['answer'][:90]}")
            # Later, the user clicks a thumb in the chat widget. Your backend receives the
            # trace_id it returned with the answer and forwards the click:
            if index % 3 != 2:  # not everybody leaves feedback
                og.log_feedback(
                    not refused,
                    trace_id=result["trace_id"],
                    user_id=user_id,
                    comment="I needed a real answer" if refused else None,
                )

        og.flush()  # send spans, pending metrics and scores now
        time.sleep(3)  # leave the platform a moment to ingest them

        step(4, "Which production answers need attention?")
        client = og.client
        failing = client.live_runs.list(failed_only=True, limit=20)
        for interaction in failing.items:
            print(f"  ! {interaction.question}")
            # Scores from the SDK (metrics, log_score, log_feedback) are the "trace scores";
            # verdicts of the platform's LLM judges are in interaction.scores.
            for score in interaction.model_dump().get("trace_scores", []):
                if score["label"] == "FAIL":
                    print(f"      {score['name']} = {score['value']}  ({score['explanation'] or '-'})")
            for verdict in interaction.scores:
                if verdict.label == "FAIL":
                    print(f"      judge {verdict.kind} = {verdict.score}  ({verdict.explanation})")
        note(
            """'Failing' = at least one score below its threshold or a thumbs-down. In the UI,
            Production -> Live -> Failing shows the same list with every score and its
            explanation. Good candidates for the gold set: promote them to a dataset
            (client.live_runs.promote) with a reviewed reference answer, and script 02 will
            test them on every change."""
        )

        step(5, "Alert rules as code")
        existing = {rule.name: rule for rule in client.alerts.list()}
        common = {
            "environment": "prod",
            "window_minutes": 60,
            "min_samples": 5,
            "webhook_url": settings.ALERT_WEBHOOK_URL,
            "webhook_format": "slack" if settings.ALERT_WEBHOOK_URL else "json",
        }
        ensure_alert(
            client,
            existing,
            name="Invented citations",
            metric="score_fail_rate",
            score_name="cites_retrieved_source",
            threshold=0.05,
            **common,
        )
        ensure_alert(
            client,
            existing,
            name="Too many hand-offs to humans",
            metric="score_fail_rate",
            score_name="resolved_by_assistant",
            threshold=0.2,
            **common,
        )
        ensure_alert(
            client,
            existing,
            name="Unhappy users",
            metric="score_fail_rate",
            score_name="user_feedback",
            threshold=0.3,
            **common,
        )
        ensure_alert(
            client, existing, name="Error rate above 5%", metric="error_rate", threshold=0.05, **common
        )
        ensure_alert(
            client,
            existing,
            name="Latency anomaly",
            metric="latency_p90_ms",
            condition="anomaly",
            operator="abs",
            threshold=3,
            **common,
        )
        note(
            """The platform checks the rules every minute on the last window of production
            data and posts to the webhook (Slack or any URL; set TOUR_ALERT_WEBHOOK_URL) when
            one fires and when it resolves. With the traffic above (4 hand-offs out of 14)
            'Too many hand-offs to humans' should fire within a minute: Production -> Alerts."""
        )

        print(f"\nDone. Open {settings.TRACKING_URI} -> Production (Health, Live, Alerts).")


if __name__ == "__main__":
    main()

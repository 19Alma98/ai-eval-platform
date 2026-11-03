"""01 - Tracing: see what your AI applications do, call by call.

Use case: "I want traces of my applications that tell me everything runs fine."

A *trace* is the record of one request (one question, one ticket, one job). It is made of
*spans*: one per step (retrieve, generate, guardrail, tool call...), each with its input,
output, duration, status and attributes. OpenGrade stores them and shows them in
Production -> Traces.

What this script shows, step by step:

  1. Trace a RAG call: ``@opengrade.trace`` + ``opengrade.span`` (code in nimbus_apps/rag.py).
  2. Add business context to a trace: user, session (conversation), tags, metadata.
  3. Trace a non-RAG app, with a guardrail and a tool span, and context for a whole block
     (``opengrade.using_attributes``), e.g. a batch job.
  4. Record failures: an exception marks the span ERROR; ``opengrade.set_error`` marks a
     handled problem (fallback answer) without raising.

Run:  uv run python 01_tracing.py
Then: UI -> Production -> Traces (project "nimbus-support").
"""

from __future__ import annotations

import sys

import opengrade

from nimbus_apps import settings
from nimbus_apps.classifier import classify_ticket
from nimbus_apps.console import note, step, title
from nimbus_apps.rag import answer_question
from nimbus_apps.retrieval import search

# ---------------------------------------------------------------------------------------
# Your own request handlers. In a real service these are your API endpoints / workers.
# ---------------------------------------------------------------------------------------


@opengrade.trace(name="chat_turn")
def handle_chat_turn(question: str, *, user_id: str, conversation_id: str, plan: str) -> dict:
    """One message of a support chat. The RAG call below becomes a child of this span."""
    # Who asked, in which conversation, with which plan. These fields are indexed: in the
    # UI you can filter "user:u-alice", "session:conv-1", "tag:plan-pro", "plan:pro".
    opengrade.set_user(user_id)
    opengrade.set_session(conversation_id)  # every turn of the conversation shares it
    opengrade.set_tags("support-chat", f"plan-{plan}")
    opengrade.set_metadata(plan=plan, channel="web")

    answer = answer_question(question)
    # Return the trace id to your frontend: it is what user feedback is attached to
    # (see 04_custom_metrics_and_monitoring.py).
    return {"answer": answer, "trace_id": opengrade.current_trace_id()}


@opengrade.trace(name="route_ticket")
def route_ticket(ticket_id: str, text: str) -> str:
    """Classify a ticket, then look up the customer when it is an account issue."""
    opengrade.set_metadata(ticket_id=ticket_id)
    queue = classify_ticket(text, model="rules-v2")

    if queue == "account":
        # Calls to your own tools/services: a TOOL span with what went in and out.
        with opengrade.span("crm.lookup_customer", kind="TOOL", input={"ticket": ticket_id}) as s:
            customer = {"tier": "business", "open_tickets": 2}  # pretend CRM call
            s.set_output(customer)
            s.set_attribute("crm.cache_hit", False)

    # A custom attribute on the current span (route_ticket): any key you like.
    opengrade.set_attribute("routing.queue", queue)
    return queue


class SearchBackendDown(RuntimeError):
    pass


@opengrade.trace(name="chat_turn_with_failing_search")
def answer_with_broken_search(question: str) -> str:
    """Simulates the vector store being down, to see what failures look like."""
    with opengrade.span("retrieve", kind="RETRIEVER", input=question):
        raise SearchBackendDown("vector store timeout after 2.0s")


@opengrade.trace(name="chat_turn_with_fallback")
def answer_with_fallback(question: str) -> str:
    """Handled problem: nothing retrieved -> canned answer. The request succeeds, but the
    trace is marked ERROR so it shows up in error rates and alerts."""
    docs = search(question, top_k=3)
    strong = [d for d in docs if float(d["score"]) >= 5.0]  # pretend relevance cut-off
    if not strong:
        opengrade.set_error("no relevant document above the relevance cut-off; used fallback")
        return "Sorry, I could not find this in our help center. A colleague will contact you."
    return answer_question(question)


# ---------------------------------------------------------------------------------------


def main() -> None:
    title("OpenGrade SDK tour - 01 Tracing")

    step(0, "Connect to the platform")
    # Three calls, once at startup:
    opengrade.set_tracking_uri(settings.TRACKING_URI)  # where the platform runs
    if opengrade.set_project(settings.PROJECT) is None:  # project (created if missing)
        sys.exit(f"OpenGrade is not reachable at {settings.TRACKING_URI}: start it first.")
    opengrade.init(
        service_name="nimbus-support",  # name of this application in the traces
        instrument="auto",  # auto-trace installed LLM SDKs (openai, anthropic, langchain...)
        version=settings.APP_VERSION,  # release of your app -> compare deploys
        environment=settings.APP_ENVIRONMENT,  # dev / staging / prod
    )
    note(f"Project '{settings.PROJECT}' at {settings.TRACKING_URI}, model {settings.DEFAULT_MODEL}")

    step(1, "One RAG call = one trace")
    answer = answer_question("How long is the password reset link valid?")
    print(f"  answer: {answer}")
    note(
        """In the UI open the trace 'support_assistant'. You will see the tree
        support_assistant -> retrieve (RETRIEVER, with the documents) -> generate ->
        llm.chat (LLM, with model, tokens and cost). Look at nimbus_apps/rag.py: the
        whole instrumentation is one decorator, two 'with opengrade.span' blocks and one
        set_retrieval_documents call."""
    )

    step(2, "Business context: users, conversations, tags, metadata")
    conversation = [
        ("u-alice", "conv-1", "pro", "How much does the Pro plan cost?"),
        ("u-alice", "conv-1", "pro", "And how long is version history kept on Business accounts?"),
        ("u-bob", "conv-2", "free", "How much storage do I get on the Free plan?"),
    ]
    for user_id, conversation_id, plan, question in conversation:
        result = handle_chat_turn(
            question, user_id=user_id, conversation_id=conversation_id, plan=plan
        )
        print(f"  [{user_id}/{conversation_id}] {question}\n      -> {result['answer']}")
        print(f"      trace_id={result['trace_id']}")
    note(
        """Production -> Traces: filter 'session:conv-1' to read Alice's whole conversation,
        'tag:plan-free' for free users, 'user:u-bob' for one customer."""
    )

    step(3, "A non-RAG app + context for a whole block (batch job)")
    tickets = {
        "T-101": "I was charged twice, please refund. Contact me at bob@example.com",
        "T-102": "I can't log in, the password reset email never arrives.",
        "T-103": "Uploads stop at 99% and then fail with an error.",
    }
    # using_attributes: every span opened inside the block gets these fields. Handy in a
    # request middleware or a batch job, where you do not want to touch each function.
    with opengrade.using_attributes(tags=["nightly-batch"], metadata={"job": "ticket-routing"}):
        for ticket_id, text in tickets.items():
            print(f"  {ticket_id} -> queue '{route_ticket(ticket_id, text)}'")
    note(
        """Open a 'route_ticket' trace: pii_guardrail (GUARDRAIL) shows the e-mail masked
        before classification; T-102 also has a crm.lookup_customer TOOL span. Filter
        'tag:nightly-batch' to see the whole job."""
    )

    step(4, "Failures: exceptions and handled errors")
    try:
        answer_with_broken_search("Can I get a refund?")
    except SearchBackendDown as exc:
        print(f"  exception propagated to the caller as usual: {exc!r}")
    print(f"  fallback answer: {answer_with_fallback('Who won the football match yesterday?')}")
    note(
        """Both traces are marked ERROR (red in the trace list) with the exception or the
        message you passed to set_error. They count in Production -> Health error rate,
        which alerts can watch (script 04). Tracing never raises in your code: if the
        platform is down, spans are dropped with a single warning."""
    )

    # Spans are sent in the background; flush before a short script exits.
    opengrade.flush()
    print(f"\nDone. Open {settings.TRACKING_URI} -> Production -> Traces.")


if __name__ == "__main__":
    main()

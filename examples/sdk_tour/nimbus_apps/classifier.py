"""A second, non-RAG application: the support-ticket classifier.

OpenGrade is not only for RAG. Any function that takes an input and returns an output
can be traced, tested on a gold set and monitored. Here a ticket is routed to one of
four queues, after a GUARDRAIL step that removes personal data before any model sees it.

Strategies (the ``model`` argument):

- ``rules-v1``: first keyword match wins (the version currently "in production").
- ``rules-v2``: weighted keywords over a larger vocabulary (the candidate).
- any other name: an LLM through the OpenAI-compatible client (see ``llm.py``).
"""

from __future__ import annotations

import re

import opengrade

from nimbus_apps.llm import chat

LABELS = ("billing", "technical", "account", "sales")

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_CARD = re.compile(r"\b(?:\d[ -]?){13,16}\b")

_RULES_V1 = {
    "billing": ["refund", "invoice", "charged"],
    "technical": ["error", "crash", "bug"],
    "account": ["password", "login", "account"],
    "sales": ["discount", "demo", "price"],
}
_RULES_V2 = {
    "billing": [
        "refund",
        "invoice",
        "charged",
        "payment",
        "vat",
        "credit card",
        "annual",
        "monthly",
    ],
    "technical": ["error", "crash", "fail", "sync", "api", "upload", "500", "bug", "slow"],
    "account": [
        "password",
        "log in",
        "login",
        "two-factor",
        "delete my account",
        "email address",
        "profile",
        "locked",
    ],
    "sales": ["discount", "demo", "enterprise", "sla", "buy", "people", "talk to", "contract"],
}


def redact_pii(text: str) -> tuple[str, int]:
    """Mask e-mail addresses and card numbers. Returns (clean text, items masked)."""
    text, emails = _EMAIL.subn("<email>", text)
    text, cards = _CARD.subn("<card>", text)
    return text, emails + cards


def _rules(text: str, rules: dict[str, list[str]], *, first_match: bool) -> str:
    lowered = text.lower()
    scores = {label: sum(kw in lowered for kw in kws) for label, kws in rules.items()}
    if first_match:
        return next((label for label, s in scores.items() if s), "technical")
    best = max(scores, key=lambda label: scores[label])
    return best if scores[best] else "technical"


@opengrade.trace(name="ticket_classifier")
def classify_ticket(text: str, model: str = "rules-v1") -> str:
    """Route a support ticket to a queue. One call = one trace."""
    opengrade.set_input(text)
    opengrade.set_metadata(app="ticket-classifier", classifier=model)

    # 1. Guardrail: never send personal data to a model. The span records how many
    #    items were masked, so you can count PII-carrying tickets in the trace list.
    with opengrade.span("pii_guardrail", kind="GUARDRAIL", input=text) as span:
        clean, masked = redact_pii(text)
        span.set_attribute("guardrail.pii_masked", masked)
        span.set_output(clean)

    # 2. Classification.
    if model == "rules-v1":
        label = _rules(clean, _RULES_V1, first_match=True)
    elif model == "rules-v2":
        label = _rules(clean, _RULES_V2, first_match=False)
    else:
        system = f"Classify the support ticket. Reply with one word among: {', '.join(LABELS)}."
        raw = chat(model, system, clean).strip().lower()
        label = next((lbl for lbl in LABELS if lbl in raw), "technical")
    return label

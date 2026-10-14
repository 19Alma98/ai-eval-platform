#!/usr/bin/env python3
"""Manual smoke: @aiobs.trace(metrics=...) + log_feedback → summary + Live.

Prereqs: docker compose up (API :8000, web :3000), CONTENT_CAPTURE_ENABLED=true.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request

import aiobs

BASE = "http://localhost:8000"
UI = "http://localhost:3000"
SLUG = "demo"


def _get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}") as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    aiobs.set_tracking_uri(BASE)
    aiobs.set_project(SLUG)
    aiobs.init(live=True, live_sample_rate=1.0)

    @aiobs.metric(threshold=0.5, requires=("documents",))
    def cites_source(s: aiobs.Sample) -> float:
        return float(any(d["id"] in (s.output or "") for d in s.documents))

    @aiobs.trace(name="smoke_answer", metrics=[cites_source], metrics_sample_rate=1.0)
    def answer(question: str) -> str:
        docs = [{"id": "pto", "text": "Full-time staff get 20 PTO days per year."}]
        aiobs.set_retrieval_documents(docs)
        return "Staff get 20 PTO days (see pto)."

    captured: dict[str, str] = {}

    @aiobs.trace(name="smoke_handle", live=True)
    def handle(question: str) -> str:
        text = answer(question)
        captured["trace_id"] = aiobs.current_trace_id() or ""
        aiobs.log_score("answer_chars", float(len(text)), threshold=1.0)
        return text

    result = handle("How many PTO days do we get?")
    trace_id = captured["trace_id"]
    assert trace_id and len(trace_id) == 32, trace_id
    print(f"output: {result!r}")
    print(f"trace_id: {trace_id}")

    ok = aiobs.log_feedback(
        True,
        trace_id=trace_id,
        user_id="smoke-user",
        comment="manual smoke thumbs-up",
    )
    print(f"log_feedback queued: {ok}")
    flushed = aiobs.flush(timeout_millis=15_000)
    print(f"flush ok: {flushed}")

    project = aiobs.get_project()
    assert project is not None
    project_id = project.id
    print(f"project_id: {project_id}")

    # Wait for OTLP → live interaction join + score ingest
    summary = None
    live = None
    for attempt in range(30):
        summary = _get(f"/api/v1/projects/{project_id}/trace-scores/summary")
        lives = _get(
            f"/api/v1/projects/{project_id}/live-interactions?limit=20"
        )
        items = lives if isinstance(lives, list) else lives.get("items") or lives.get("data") or []
        for item in items:
            meta = item.get("metadata") or {}
            src = meta.get("source_trace_id") or ""
            scores = item.get("trace_scores") or []
            if src.lower() == trace_id.lower() or any(
                (s.get("trace_id") or "").lower() == trace_id.lower() for s in scores
            ):
                live = item
                break
        rows = (summary or {}).get("rows") or []
        if rows and live and (live.get("trace_scores") or []):
            break
        time.sleep(0.5)
    else:
        print("TIMEOUT waiting for summary rows + live interaction with trace_scores", file=sys.stderr)
        print("summary:", json.dumps(summary, indent=2), file=sys.stderr)
        print("live:", json.dumps(live, indent=2) if live else None, file=sys.stderr)
        return 1

    print("\n=== /trace-scores/summary ===")
    print(json.dumps(summary, indent=2))

    print("\n=== live interaction (SDK scores & feedback) ===")
    detail = _get(f"/api/v1/live-interactions/{live['id']}")
    print(
        json.dumps(
            {
                "id": detail.get("id"),
                "question": detail.get("question"),
                "answer": detail.get("answer"),
                "trace_scores": detail.get("trace_scores"),
                "metadata": detail.get("metadata"),
            },
            indent=2,
        )
    )

    names = {s.get("name") for s in detail.get("trace_scores") or []}
    sources = {s.get("source") for s in detail.get("trace_scores") or []}
    print(f"\nscore names: {sorted(names)}")
    print(f"sources: {sorted(sources)}")
    print(f"UI: {UI}/live-runs?project={project_id}")
    print(f"detail: {UI}/live-runs/{live['id']}?project={project_id}")

    need = {"cites_source", "user_feedback", "answer_chars"}
    missing = need - names
    if missing:
        print(f"MISSING scores: {missing}", file=sys.stderr)
        return 1
    if "human" not in sources or "sdk" not in sources:
        print(f"unexpected sources: {sources}", file=sys.stderr)
        return 1
    print("\nSMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

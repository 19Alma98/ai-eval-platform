#!/usr/bin/env python3
"""Simulate production → AI Eval Run (Live runs) flow.

Submits a few prod-like Q/A/document turns via ``client.live_runs.submit``,
waits for the background gold-less judge (or triggers rescore), then prints
status so you can open the Live runs UI.

Requires:
  - API up (default http://localhost:8000)
  - migrations applied (incl. live_interactions)
  - LLM judge configured on the API (same as TestSet groundedness)
  - SDK deps available (prefer running via the sdk env — see Usage)

Usage (from repo root)::

    export AIOBS_API_BASE_URL=http://localhost:8000
    cd sdk && uv run python ../scripts/live_run_demo.py

    # or, with sdk/.venv activated:
    #   python ../scripts/live_run_demo.py --project-slug acme-people-ops
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SDK_DIR = ROOT / "sdk"
sys.path.insert(0, str(SDK_DIR / "src"))

from aiobs import AiobsAPIError, Client  # noqa: E402
from aiobs._http import resolve_api_base_url  # noqa: E402

KNOWLEDGE_PATH = ROOT / "examples" / "hr_it_assistant" / "knowledge.json"


def ensure_project(client: Client, slug: str, name: str) -> dict[str, Any]:
    for project in client.projects.list():
        if project.get("slug") == slug:
            print(f"reusing project {slug} ({project['id']})")
            return project
    project = client.projects.create(name=name, slug=slug)
    print(f"created project {slug} ({project['id']})")
    return project


def load_docs() -> dict[str, dict[str, str]]:
    data = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    return {
        str(doc["id"]): {
            "id": str(doc["id"]),
            "title": str(doc.get("title") or doc["id"]),
            "text": str(doc.get("body") or ""),
        }
        for doc in data
    }


def sample_turns(docs: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    """Prod-like turns: grounded, hallucinated, empty retrieval."""
    pto = docs["pto"]
    vpn = docs["vpn"]
    return [
        {
            "label": "grounded",
            "question": "How many PTO days do full-time employees get per year?",
            "answer": "Full-time employees receive 20 days of paid time off per calendar year.",
            "documents": [pto],
            "metadata": {"env": "prod-sim", "scenario": "grounded"},
        },
        {
            "label": "hallucination",
            "question": "How many PTO days do full-time employees get per year?",
            "answer": "Everyone gets unlimited PTO and can take sabbaticals every quarter.",
            "documents": [pto],
            "metadata": {"env": "prod-sim", "scenario": "hallucination"},
        },
        {
            "label": "grounded_vpn",
            "question": "Which VPN client should I use for remote access?",
            "answer": "Use the Acme GlobalProtect VPN with MFA on every login.",
            "documents": [vpn],
            "metadata": {"env": "prod-sim", "scenario": "grounded"},
        },
        {
            "label": "empty_docs",
            "question": "Where do I submit expense reports?",
            "answer": "Submit them in Concur within 30 days.",
            "documents": [],
            "metadata": {"env": "prod-sim", "scenario": "empty_retrieval"},
        },
    ]


def wait_until_scored(
    client: Client,
    interaction_id: str,
    *,
    timeout_s: float,
    poll_s: float,
) -> Any:
    deadline = time.monotonic() + timeout_s
    last: Any = None
    while time.monotonic() < deadline:
        last = client.live_runs.get(interaction_id)
        status = str(last.judge_status or "")
        if status in {"scored", "error"}:
            return last
        time.sleep(poll_s)
    print(f"  timeout waiting; calling rescore for {interaction_id[:8]}…")
    return client.live_runs.rescore(interaction_id)


def summarize(interaction: Any) -> str:
    status = interaction.judge_status
    scores = interaction.scores or []
    parts = []
    for s in scores:
        parts.append(f"{s.kind}={s.score} ({s.label})")
    score_txt = ", ".join(parts) if parts else "(no scores)"
    warn = interaction.score_warning or interaction.error_message
    extra = f" — {warn}" if warn else ""
    return f"{status}: {score_txt}{extra}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=None, help="API base (or AIOBS_API_BASE_URL)")
    parser.add_argument("--project-slug", default="live-demo")
    parser.add_argument("--project-name", default="Live Run Demo")
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Submit only; do not wait/rescore (check UI after background judge)",
    )
    parser.add_argument("--timeout", type=float, default=90.0, help="Seconds to wait per turn")
    parser.add_argument(
        "--promote",
        action="store_true",
        help="Promote the first grounded turn to a dataset",
    )
    args = parser.parse_args()

    base = resolve_api_base_url(args.base_url)
    client = Client(base)
    print(f"API: {base}")

    health = client.health()
    print(f"health: {health}")

    project = ensure_project(client, args.project_slug, args.project_name)
    project_id = project["id"]

    pack = client.metrics_packs.ensure(project_id)
    kinds = [e.kind for e in pack.entries]
    print(f"metrics pack: {', '.join(str(k) for k in kinds)}")

    docs = load_docs()
    turns = sample_turns(docs)
    stamp = uuid.uuid4().hex[:8]
    submitted: list[dict[str, Any]] = []

    print(f"\nSubmitting {len(turns)} prod-sim turns…")
    for turn in turns:
        external_id = f"live-demo-{stamp}-{turn['label']}"
        result = client.live_runs.submit(
            project_id,
            question=turn["question"],
            answer=turn["answer"],
            documents=turn["documents"],
            metadata=turn["metadata"],
            external_id=external_id,
        )
        submitted.append({"id": result.id, "_label": turn["label"]})
        print(
            f"  [{turn['label']}] id={result.id[:8]}… "
            f"status={result.judge_status} external_id={external_id}"
        )

    if not args.no_wait:
        print("\nWaiting for judge (background, then rescore if needed)…")
        for item in submitted:
            detail = wait_until_scored(
                client,
                item["id"],
                timeout_s=args.timeout,
                poll_s=2.0,
            )
            print(f"  [{item['_label']}] {summarize(detail)}")

    if args.promote and submitted:
        target = next((s for s in submitted if s["_label"] == "grounded"), submitted[0])
        dataset = client.datasets.create(
            project_id,
            name=f"from-live-{stamp}",
            description="Promoted from live_run_demo",
            task_type="rag_qa",
        )
        # Gold is written by a reviewer, never copied from the prod answer/retrieval.
        item = client.live_runs.promote(
            target["id"],
            dataset_id=dataset.id,
            expected_output="Full-time employees get 20 PTO days per calendar year.",
            expected_doc_ids=["pto"],
        )
        print(
            f"\npromoted [{target['_label']}] → dataset {dataset.name} "
            f"item {item.id[:8]}…"
        )

    listed = client.live_runs.list(project_id, limit=20)
    print(f"\nLive interactions in project: {len(listed.items)}")
    failed = client.live_runs.list(project_id, failed_only=True, limit=20)
    if failed.items:
        print(f"Failed-only: {len(failed.items)} (promote candidates for the next TestSet)")
    print(f"Open UI: http://localhost:3000/live-runs?project={project_id}")
    print("Nav: Live runs — inspect scores, Agree/Disagree, Promote to TestSet")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AiobsAPIError as exc:
        print(f"API error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except ModuleNotFoundError as exc:
        print(
            f"{exc}\n"
            "Install SDK deps, then re-run:\n"
            "  cd sdk && uv sync --extra dev && uv run python ../scripts/live_run_demo.py\n",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    except Exception as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc

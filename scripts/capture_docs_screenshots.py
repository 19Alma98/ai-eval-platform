"""Capture getting-started PNGs from a running OpenGrade UI."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "images"
UI = os.getenv("OPENGRADE_UI_URL", "http://127.0.0.1:8000").rstrip("/")
PROJECT_SLUG = os.getenv("OPENGRADE_PROJECT_SLUG", "demo")
EXPERIMENT_NAME = os.getenv("OPENGRADE_EXPERIMENT_NAME", "getting-started-bonus")


def _get_json(path: str) -> object:
    req = urllib.request.Request(f"{UI}{path}", headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def resolve_demo_context() -> tuple[str, str, str]:
    """Return (project_id, trace_id, experiment_id) for seeded demo data."""
    projects = _get_json("/api/v1/projects")
    if not isinstance(projects, list):
        raise RuntimeError("Unexpected /api/v1/projects response")
    project = next((p for p in projects if p.get("slug") == PROJECT_SLUG), None)
    if not project:
        raise RuntimeError(
            f"No project with slug {PROJECT_SLUG!r}. Run getting_started_core.py first."
        )
    project_id = project["id"]

    traces_payload = _get_json(
        f"/api/v1/projects/{project_id}/traces?limit=20"
    )
    items = traces_payload.get("items") if isinstance(traces_payload, dict) else None
    if not items:
        raise RuntimeError("No traces in demo project.")
    preferred = next(
        (t for t in items if t.get("name") == "__main__.ask"),
        items[0],
    )
    trace_id = preferred["trace_id"]

    experiments = _get_json(f"/api/v1/projects/{project_id}/experiments")
    if not isinstance(experiments, list) or not experiments:
        raise RuntimeError("No experiments in demo project.")
    experiment = next(
        (e for e in experiments if e.get("name") == EXPERIMENT_NAME),
        experiments[0],
    )
    experiment_id = experiment["id"]

    return project_id, trace_id, experiment_id


def _with_project(path: str, project_id: str) -> str:
    sep = "&" if "?" in path else "?"
    return f"{UI}{path}{sep}project={project_id}"


def _wait_overview(page, project_id: str) -> None:
    page.goto(_with_project("/overview", project_id), wait_until="networkidle")
    page.get_by_role("heading", name="Overview").wait_for(state="visible", timeout=20_000)
    page.get_by_text("Offline", exact=True).wait_for(state="visible", timeout=20_000)
    page.get_by_text("getting-started-bonus", exact=False).wait_for(
        state="visible", timeout=20_000
    )


def _wait_trace_waterfall(page, project_id: str, trace_id: str) -> None:
    page.goto(
        _with_project(f"/traces/{trace_id}", project_id),
        wait_until="networkidle",
    )
    page.get_by_role("heading", name="__main__.ask").wait_for(
        state="visible", timeout=20_000
    )
    page.get_by_role("tab", name="Timeline").click()
    page.get_by_text("Span", exact=True).first.wait_for(state="visible", timeout=20_000)
    page.wait_for_timeout(500)


def _wait_experiment_detail(page, project_id: str, experiment_id: str) -> None:
    page.goto(
        _with_project(f"/experiments/{experiment_id}", project_id),
        wait_until="networkidle",
    )
    page.get_by_role("heading", name=EXPERIMENT_NAME).wait_for(
        state="visible", timeout=20_000
    )
    page.get_by_text("Test set", exact=False).first.wait_for(state="visible", timeout=20_000)
    page.wait_for_timeout(500)


def main() -> None:
    try:
        project_id, trace_id, experiment_id = resolve_demo_context()
    except (urllib.error.URLError, TimeoutError, RuntimeError) as e:
        print(f"Setup failed: {e}", file=sys.stderr)
        sys.exit(1)

    OUT.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})

        try:
            _wait_overview(page, project_id)
            page.screenshot(path=str(OUT / "ui-overview.png"), full_page=False)

            _wait_trace_waterfall(page, project_id, trace_id)
            page.screenshot(path=str(OUT / "ui-trace-waterfall.png"), full_page=False)

            _wait_experiment_detail(page, project_id, experiment_id)
            page.screenshot(path=str(OUT / "ui-experiment.png"), full_page=False)
        except PlaywrightTimeout as e:
            print(f"Capture timed out: {e}", file=sys.stderr)
            browser.close()
            sys.exit(1)

        browser.close()

    for name in ("ui-overview.png", "ui-trace-waterfall.png", "ui-experiment.png"):
        path = OUT / name
        size = path.stat().st_size
        if size < 20_000:
            print(
                f"Warning: {name} is only {size} bytes (expected >20KB)",
                file=sys.stderr,
            )

    print(f"Wrote PNGs under {OUT} (project={project_id}, trace={trace_id})")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(e, file=sys.stderr)
        sys.exit(1)

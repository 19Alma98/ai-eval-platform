from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from opengrade_server.cli_report import render_junit, render_markdown

PAYLOAD: dict[str, Any] = {
    "experiment_id": "11111111-2222-3333-4444-555555555555",
    "name": "rag-ci",
    "url": "http://og/experiments/1",
    "version": "abc1234",
    "git": {"commit": "abc1234def", "branch": "feature"},
    "baseline_ref": "alias:main",
    "baseline_id": "99999999-2222-3333-4444-555555555555",
    "baseline_git": {"commit": "0123456789"},
    "code_diff_url": "https://github.com/o/r/compare/0123456789...abc1234def",
    "notes": [],
    "comparison": [
        {
            "metric": "hit_at_k",
            "candidate": 0.8,
            "baseline": 1.0,
            "delta": -0.2,
            "status": "regression",
        }
    ],
    "gate": "failed",
    "checks": [
        {"metric": "hit_at_k.min", "actual": 0.8, "threshold": 0.8, "status": "passed"},
        {
            "metric": "regression.hit_at_k.mean_score",
            "actual": -0.2,
            "threshold": -0.05,
            "status": "failed",
        },
        {
            "metric": "latency.p95.max_increase_pct",
            "actual": 31.4,
            "threshold": 20.0,
            "status": "failed",
        },
        {
            "metric": "cost.mean_per_request_usd.max_increase_pct",
            "actual": None,
            "threshold": 10.0,
            "status": "unavailable",
        },
    ],
}


def test_markdown_lists_failures_first_and_comparison() -> None:
    md = render_markdown(PAYLOAD)
    assert md.startswith("## ❌ OpenGrade quality gate: FAILED")
    assert "[rag-ci](http://og/experiments/1)" in md
    assert "`alias:main` → `99999999`" in md
    assert "[diff](https://github.com/o/r/compare/" in md
    assert "**1 of 4 checks passed**" in md
    failing = md.split("### Failing checks")[1].split("###")[0]
    assert "hit_at_k.min" not in failing
    assert "| `regression.hit_at_k.mean_score` | -0.200 |" in failing
    assert "| `latency.p95.max_increase_pct` | +31.4% | ≤ 20% |" in failing
    assert "⚠️ unavailable" in failing
    assert "| hit_at_k | 0.800 | 1.000 | -0.200 | 🔻 regression |" in md
    assert "<details><summary>All checks (4)</summary>" in md


def test_markdown_without_policy_and_with_notes() -> None:
    md = render_markdown(
        {
            "experiment_id": "e",
            "metrics": {"hit_at_k": 1.0},
            "gate": None,
            "notes": ["No baseline: alias 'main' is not set."],
        }
    )
    assert "evaluated (no policy)" in md
    assert "> ⚠️ No baseline: alias 'main' is not set." in md
    assert "| **Baseline** | none | — |" in md
    assert "| hit_at_k | 1.000 |" in md


def test_junit_one_case_per_check_unavailable_is_failure() -> None:
    root = ET.fromstring(render_junit(PAYLOAD))
    suite = root.find("testsuite")
    assert suite is not None
    assert suite.get("tests") == "4" and suite.get("failures") == "3"
    cases = {c.get("name"): c for c in suite.findall("testcase")}
    assert cases["hit_at_k.min"].find("failure") is None
    failure = cases["latency.p95.max_increase_pct"].find("failure")
    assert failure is not None and "+31.4%" in (failure.get("message") or "")
    unavailable = cases["cost.mean_per_request_usd.max_increase_pct"].find("failure")
    assert unavailable is not None and unavailable.get("type") == "unavailable"

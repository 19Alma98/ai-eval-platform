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


REGRESSED: dict[str, Any] = {
    **PAYLOAD,
    "compare_url": "http://og/experiments/1/compare?baseline=9",
    "regressed_items_total": 3,
    "regressed_items": [
        {
            "dataset_item_id": "a",
            "input": "Which VPN | client?\nsecond line",
            "expected_output": "GlobalProtect",
            "baseline_output": "Use GlobalProtect.",
            "candidate_output": "<details>broken</details> I don't know.",
            "metrics": [
                {
                    "metric": "hit_at_k",
                    "baseline_score": 1.0,
                    "candidate_score": 0.0,
                    "baseline_label": "PASS",
                    "candidate_label": "FAIL",
                    "delta": -1.0,
                    "explanation": "no expected doc in top-k retrieved",
                }
            ],
        },
        {
            "dataset_item_id": "b",
            "input": {"question": "PTO days?"},
            "expected_output": None,
            "baseline_output": "20 days",
            "candidate_output": "x" * 500,
            "metrics": [
                {
                    "metric": "correctness",
                    "baseline_score": 0.9,
                    "candidate_score": 0.4,
                    "baseline_label": None,
                    "candidate_label": None,
                    "delta": -0.5,
                    "explanation": None,
                }
            ],
        },
    ],
}


def test_markdown_lists_regressed_cases_escaped() -> None:
    md = render_markdown(REGRESSED)
    section = md.split("### Test cases worse than baseline (2 of 3)")[1]
    table = section.split("<details>")[0]
    # one table row per case; pipes / newlines / HTML in model text cannot break it
    assert "| 1 | Which VPN \\| client? second line | hit_at_k: 1.000 PASS → 0.000 FAIL |" in table
    assert "&lt;details&gt;broken&lt;/details&gt; I don't know." in table
    assert '| 2 | {"question": "PTO days?"} | correctness: 0.900 → 0.400 |' in table
    assert "x" * 119 + "…" in table and "x" * 121 not in table
    full = section.split("<details><summary>Full outputs</summary>")[1]
    assert "Why (hit_at_k):<pre>no expected doc in top-k retrieved</pre>" in full
    assert "Expected:" not in full.split("**#2**")[1]  # no expected output → no block
    assert "[All test cases side by side](http://og/experiments/1/compare?baseline=9)" in md


def test_junit_regression_failure_lists_cases() -> None:
    root = ET.fromstring(render_junit(REGRESSED))
    cases = {c.get("name"): c for c in root.iter("testcase")}
    failure = cases["regression.hit_at_k.mean_score"].find("failure")
    assert failure is not None and failure.text is not None
    assert "- Which VPN | client? second line: 1.000 PASS → 0.000 FAIL" in failure.text
    other = cases["latency.p95.max_increase_pct"].find("failure")
    assert other is not None and "VPN" not in (other.text or "")

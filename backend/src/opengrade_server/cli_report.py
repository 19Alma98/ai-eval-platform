"""CI reports for ``opengrade evaluate`` / ``opengrade check``: Markdown and JUnit XML.

Both render the same payload the CLI prints with ``--json`` (``gate``, ``checks``, plus,
for ``evaluate``, experiment / baseline / git / comparison fields). The Markdown fits a
GitHub job summary (``--report-md "$GITHUB_STEP_SUMMARY"``) or a sticky PR comment; the
JUnit file is picked up by CI test-report widgets (GitLab, Jenkins, Azure, GitHub actions
that parse JUnit).
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

_STATUS_ICON = {"passed": "✅", "failed": "❌"}
_VERDICT_ICON = {"regression": "🔻", "improved": "🔺", "unchanged": "＝"}
BASELINE_REQUIRED_CHECK = "baseline.required"


def _num(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool) or not isinstance(value, int | float):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        return "—"
    if abs(value) >= 100:
        return f"{value:,.0f}" if value.is_integer() else f"{value:,.1f}"
    if value == 0 or abs(value) >= 0.001:
        return f"{value:.3f}"
    return f"{value:.2g}"


def _signed(value: Any) -> str:
    if value is None or isinstance(value, bool) or not isinstance(value, int | float):
        return "—"
    return f"{value:+.3f}"


def _signed_pct(value: Any) -> str:
    if value is None or isinstance(value, bool) or not isinstance(value, int | float):
        return "—"
    return f"{value:+.1f}%"


def _check_value(metric: str, value: Any) -> str:
    if metric.endswith("_pct"):
        return _signed_pct(value)
    if ".regression." in metric or metric.startswith("regression."):
        return _signed(value)
    return _num(value)


def _check_threshold(metric: str, threshold: Any) -> str:
    if metric == BASELINE_REQUIRED_CHECK:
        return "a comparable baseline"
    if threshold is None:
        if ".regression." in metric or metric.startswith("regression."):
            return "no significant drop"
        return "—"
    if metric.endswith("_pct"):
        return f"≤ {threshold:g}%"
    if metric.endswith(".min"):
        return f"≥ {_num(threshold)}"
    if ".regression." in metric or metric.startswith("regression."):
        return f"no significant drop, Δ ≥ {_signed(threshold)}"
    return f"≤ {_num(threshold)}"


def _commit(git: dict[str, Any] | None) -> str:
    if not git or not git.get("commit"):
        return "—"
    text = f"`{str(git['commit'])[:7]}`"
    if git.get("branch"):
        text += f" ({git['branch']})"
    if git.get("dirty"):
        text += " + uncommitted"
    return text


def _check_rows(checks: list[dict[str, Any]]) -> list[str]:
    rows = ["| Check | Actual | Threshold | Status |", "|---|---|---|---|"]
    for check in checks:
        metric = str(check.get("metric", ""))
        status = str(check.get("status", ""))
        icon = _STATUS_ICON.get(status, "⚠️")
        rows.append(
            f"| `{metric}` | {_check_value(metric, check.get('actual'))} "
            f"| {_check_threshold(metric, check.get('threshold'))} | {icon} {status} |"
        )
    return rows


def render_markdown(payload: dict[str, Any], *, title: str = "OpenGrade quality gate") -> str:
    gate = payload.get("gate")
    checks: list[dict[str, Any]] = list(payload.get("checks") or [])
    if gate is None:
        head = f"## ℹ️ {title}: evaluated (no policy)"
    else:
        icon = _STATUS_ICON.get(str(gate), "⚠️")
        head = f"## {icon} {title}: {str(gate).upper()}"
    lines = [head, ""]

    if payload.get("experiment_id"):
        name = payload.get("name") or str(payload["experiment_id"])[:8]
        url = payload.get("url")
        experiment = f"[{name}]({url})" if url else f"`{name}`"
        version = f" · version `{payload['version']}`" if payload.get("version") else ""
        lines += ["| | Experiment | Code |", "|---|---|---|"]
        lines.append(f"| **Candidate** | {experiment}{version} | {_commit(payload.get('git'))} |")
        baseline_id = payload.get("baseline_id")
        if baseline_id:
            ref = payload.get("baseline_ref")
            label = f"`{ref}` → `{str(baseline_id)[:8]}`" if ref else f"`{str(baseline_id)[:8]}`"
            code = _commit(payload.get("baseline_git"))
            if payload.get("code_diff_url"):
                code += f" · [diff]({payload['code_diff_url']})"
            lines.append(f"| **Baseline** | {label} | {code} |")
        else:
            lines.append("| **Baseline** | none | — |")
        lines.append("")

    for note in payload.get("notes") or []:
        lines += [f"> ⚠️ {note}", ""]

    promoted = payload.get("promoted")
    if promoted:
        lines += [f"Promoted: alias `{promoted['alias']}` → `{str(promoted['experiment_id'])[:8]}`"]
        lines.append("")

    if checks:
        failed = [c for c in checks if c.get("status") != "passed"]
        lines.append(f"**{len(checks) - len(failed)} of {len(checks)} checks passed**")
        lines.append("")
        if failed:
            lines += ["### Failing checks", "", *_check_rows(failed), ""]

    comparison: list[dict[str, Any]] = list(payload.get("comparison") or [])
    metrics: dict[str, Any] = dict(payload.get("metrics") or {})
    if comparison:
        lines += [
            "### Metrics vs baseline",
            "",
            "| Metric | Candidate | Baseline | Δ | Verdict |",
            "|---|---|---|---|---|",
        ]
        for row in comparison:
            verdict = str(row.get("status") or "—")
            cell = f"{_VERDICT_ICON.get(verdict, '')} {verdict}".strip()
            lines.append(
                f"| {row.get('metric')} | {_num(row.get('candidate'))} "
                f"| {_num(row.get('baseline'))} | {_signed(row.get('delta'))} | {cell} |"
            )
        lines.append("")
    elif metrics:
        lines += ["### Metrics", "", "| Metric | Mean |", "|---|---|"]
        lines += [f"| {name} | {_num(value)} |" for name, value in metrics.items()]
        lines.append("")

    if checks:
        lines += [
            f"<details><summary>All checks ({len(checks)})</summary>",
            "",
            *_check_rows(checks),
            "",
            "</details>",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def render_junit(payload: dict[str, Any], *, suite: str = "opengrade quality gate") -> str:
    """One ``<testcase>`` per gate check; ``failed`` and ``unavailable`` are failures
    (both fail the gate)."""
    checks: list[dict[str, Any]] = list(payload.get("checks") or [])
    failures = sum(1 for c in checks if c.get("status") != "passed")
    root = ET.Element("testsuites", name="opengrade", tests=str(len(checks)))
    root.set("failures", str(failures))
    ts = ET.SubElement(root, "testsuite", name=suite, tests=str(len(checks)))
    ts.set("failures", str(failures))
    ts.set("errors", "0")
    ts.set("skipped", "0")
    props = ET.SubElement(ts, "properties")
    for key in ("experiment_id", "url", "version", "baseline_id", "gate"):
        if payload.get(key) is not None:
            ET.SubElement(props, "property", name=key, value=str(payload[key]))
    for check in checks:
        metric = str(check.get("metric", ""))
        case = ET.SubElement(ts, "testcase", classname="opengrade.gate", name=metric)
        status = check.get("status")
        if status == "passed":
            continue
        actual = _check_value(metric, check.get("actual"))
        threshold = _check_threshold(metric, check.get("threshold"))
        if status == "failed":
            message = f"actual {actual}, required {threshold}"
        else:
            message = f"{status}: no data to evaluate (fails the gate); required {threshold}"
        failure = ET.SubElement(case, "failure", message=message, type=str(status))
        failure.text = message
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def write_reports(
    payload: dict[str, Any], *, markdown: Path | None, junit: Path | None, title: str | None = None
) -> None:
    if markdown is not None:
        kwargs = {"title": title} if title else {}
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text(render_markdown(payload, **kwargs), encoding="utf-8")
    if junit is not None:
        junit.parent.mkdir(parents=True, exist_ok=True)
        junit.write_text(render_junit(payload), encoding="utf-8")

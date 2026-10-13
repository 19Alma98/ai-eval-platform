"""Offline judge sanity suite on the HR gold set with synthetic known-good/bad answers.

Not part of default PR CI. Run manually (or via the optional workflow example) against a
real judge model.

Usage (from backend/):
    LLM_MODEL=ollama/gemma4:e2b LLM_API_BASE=http://localhost:11434 \
        uv run python ../scripts/judge_sanity.py [--variants good,wrong_fact] [--method rubric]

Exit codes: 0 pass | 1 threshold failure | 2 config / runtime error
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "examples" / "hr_it_assistant"
sys.path.insert(0, str(APP_DIR))

from aiobs_server.config import get_settings  # noqa: E402
from aiobs_server.evaluation import bootstrap_evaluators, create_evaluator  # noqa: E402
from aiobs_server.evaluation.judges.evaluators import (  # noqa: E402
    JUDGE_KINDS,
    JudgeDefaults,
    create_llm_judge,
)
from aiobs_server.evaluation.protocol import EvaluationSample  # noqa: E402
from aiobs_server.infrastructure.llm import LiteLlmClient  # noqa: E402
from judge_sanity_lib import (  # noqa: E402
    METRIC_KINDS,
    VARIANTS,
    build_variant_samples,
    check_thresholds,
    iter_gold_items,
    load_thresholds,
    mean_applicable,
)
from kb import load_knowledge  # noqa: E402


def _parse_variants(raw: str | None) -> list[str]:
    if not raw or raw.strip() in {"*", "all"}:
        return list(VARIANTS)
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    unknown = [p for p in parts if p not in VARIANTS]
    if unknown:
        raise SystemExit(f"unknown variants: {', '.join(unknown)}; choose from {VARIANTS}")
    return parts


def _sample_from_dict(row: dict[str, Any]) -> EvaluationSample:
    return EvaluationSample(
        input=row["input"],
        expected_output=row["expected_output"],
        actual_output=row["actual_output"],
        context=row["context"],
        metadata=dict(row["metadata"]),
    )


_RAW_LOG_LIMIT = 800


def _log_judge_error(
    *,
    variant: str,
    item_index: int,
    kind: str,
    result: Any,
) -> None:
    """Print ERROR / judge_output_invalid details for prompt-engineering diagnosis."""
    meta = result.metadata or {}
    error_type = meta.get("error_type")
    if result.label != "ERROR" and error_type != "judge_output_invalid":
        return
    raw = meta.get("raw_output")
    raw_shown = ""
    if isinstance(raw, str) and raw.strip():
        clipped = raw if len(raw) <= _RAW_LOG_LIMIT else raw[:_RAW_LOG_LIMIT] + "…"
        raw_shown = f"\n    raw_output: {clipped!r}"
    print(
        f"  ! ERROR item={item_index} kind={kind} "
        f"error_type={error_type!r} explanation={result.explanation!r}"
        f"{raw_shown}",
        file=sys.stderr,
    )


async def _score_variant(
    *,
    variant: str,
    samples: list[dict[str, Any]],
    llm: LiteLlmClient,
    defaults: JudgeDefaults,
    method: str | None,
) -> dict[str, float | None]:
    bootstrap_evaluators()
    judge_config = {"method": method} if method else {}
    judges = {
        kind: create_llm_judge(
            kind, judge_config if kind != "answer_relevance" else {}, llm, defaults=defaults
        )
        for kind in JUDGE_KINDS
        if kind in METRIC_KINDS
    }
    hit = create_evaluator("hit_at_k", {"k": 5})

    scores: dict[str, list[float | None]] = {kind: [] for kind in METRIC_KINDS}
    for item_index, row in enumerate(samples):
        sample = _sample_from_dict(row)
        for kind, judge in judges.items():
            result = await judge.evaluate(sample)
            scores[kind].append(result.score)
            _log_judge_error(
                variant=variant, item_index=item_index, kind=kind, result=result
            )
        hit_result = await hit.evaluate(sample)
        scores["hit_at_k"].append(hit_result.score)

    return {kind: mean_applicable(vals) for kind, vals in scores.items()}


async def run(
    *,
    variants: list[str],
    method: str | None,
    thresholds_path: Path,
) -> int:
    settings = get_settings()
    if not settings.llm_model:
        print("LLM_MODEL is not set", file=sys.stderr)
        return 2

    try:
        thresholds = load_thresholds(thresholds_path)
    except (OSError, ValueError) as exc:
        print(f"failed to load thresholds: {exc}", file=sys.stderr)
        return 2

    docs = load_knowledge()
    n_gold = len(iter_gold_items(docs))
    llm = LiteLlmClient(settings)
    defaults = JudgeDefaults(model=settings.llm_model)
    aggregates: dict[str, dict[str, float | None]] = {}

    print(
        f"judge model={settings.llm_model} gold_items={n_gold} "
        f"variants={','.join(variants)}"
    )
    for variant in variants:
        samples = build_variant_samples(variant, docs=docs)
        print(f"\n== variant={variant} n={len(samples)}")
        aggregates[variant] = await _score_variant(
            variant=variant,
            samples=samples,
            llm=llm,
            defaults=defaults,
            method=method,
        )
        for kind, value in aggregates[variant].items():
            shown = "n/a" if value is None else f"{value:.3f}"
            print(f"  {kind}: {shown}")

    failures = check_thresholds(aggregates, thresholds)
    print("\n== summary")
    print(json.dumps(aggregates, indent=2, default=str))
    if failures:
        print("THRESHOLD FAILURES:", file=sys.stderr)
        for msg in failures:
            print(f"  - {msg}", file=sys.stderr)
        return 1
    print("all checked thresholds passed")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--variants",
        default="all",
        help=f"comma-separated subset of {','.join(VARIANTS)} (default: all)",
    )
    parser.add_argument("--method", choices=["claims", "rubric"], default=None)
    parser.add_argument(
        "--thresholds",
        type=Path,
        default=APP_DIR / "judge_sanity_thresholds.yaml",
    )
    args = parser.parse_args()
    variants = _parse_variants(args.variants)
    try:
        code = asyncio.run(
            run(variants=variants, method=args.method, thresholds_path=args.thresholds)
        )
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(f"judge sanity failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    raise SystemExit(code)


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import re
from typing import Any

from aiobs_server.evaluation.outcomes import fail_min, pass_, skip
from aiobs_server.evaluation.protocol import EvaluationResult, EvaluationSample
from aiobs_server.evaluation.registry import register_evaluator


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, default=str)


def _as_context(sample: EvaluationSample) -> dict[str, Any]:
    if sample.context is None:
        return {}
    if isinstance(sample.context, dict):
        return sample.context
    return {"value": sample.context}


class ExactMatchEvaluator:
    name = "exact_match"

    def __init__(self, config: dict[str, Any]) -> None:
        self._case_sensitive = bool(config.get("case_sensitive", True))

    async def evaluate(self, sample: EvaluationSample) -> EvaluationResult:
        if sample.actual_output is None:
            return EvaluationResult(
                score=None, label="SKIPPED", explanation="actual_output is missing"
            )
        if sample.expected_output is None:
            return EvaluationResult(
                score=None, label="SKIPPED", explanation="expected_output is missing"
            )
        actual = _stringify(sample.actual_output)
        expected = _stringify(sample.expected_output)
        if not self._case_sensitive:
            actual = actual.lower()
            expected = expected.lower()
        matched = actual == expected
        return EvaluationResult(
            score=1.0 if matched else 0.0,
            label="PASS" if matched else "FAIL",
            explanation="exact match" if matched else "values differ",
            metadata={"case_sensitive": self._case_sensitive},
        )


class ContainsEvaluator:
    name = "contains"

    def __init__(self, config: dict[str, Any]) -> None:
        self._substring = config.get("substring")
        self._case_sensitive = bool(config.get("case_sensitive", True))

    async def evaluate(self, sample: EvaluationSample) -> EvaluationResult:
        if sample.actual_output is None:
            return EvaluationResult(
                score=None, label="SKIPPED", explanation="actual_output is missing"
            )
        needle = self._substring
        if needle is None:
            needle = sample.expected_output
        if needle is None:
            return EvaluationResult(
                score=None,
                label="SKIPPED",
                explanation="substring/expected_output is missing",
            )
        haystack = _stringify(sample.actual_output)
        target = _stringify(needle)
        if not self._case_sensitive:
            haystack = haystack.lower()
            target = target.lower()
        found = target in haystack
        return EvaluationResult(
            score=1.0 if found else 0.0,
            label="PASS" if found else "FAIL",
            explanation="substring found" if found else "substring not found",
        )


class RegexEvaluator:
    name = "regex"

    def __init__(self, config: dict[str, Any]) -> None:
        pattern = config.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            raise ValueError("regex evaluator requires config.pattern")
        flags = 0
        if config.get("ignore_case"):
            flags |= re.IGNORECASE
        self._pattern = re.compile(pattern, flags)

    async def evaluate(self, sample: EvaluationSample) -> EvaluationResult:
        if sample.actual_output is None:
            return EvaluationResult(
                score=None, label="SKIPPED", explanation="actual_output is missing"
            )
        text = _stringify(sample.actual_output)
        matched = self._pattern.search(text) is not None
        return EvaluationResult(
            score=1.0 if matched else 0.0,
            label="PASS" if matched else "FAIL",
            explanation="regex matched" if matched else "regex did not match",
            metadata={"pattern": self._pattern.pattern},
        )


class JsonSchemaEvaluator:
    name = "json_schema"

    def __init__(self, config: dict[str, Any]) -> None:
        schema = config.get("schema")
        if not isinstance(schema, dict):
            raise ValueError("json_schema evaluator requires config.schema object")
        self._schema = schema

    async def evaluate(self, sample: EvaluationSample) -> EvaluationResult:
        if sample.actual_output is None:
            return EvaluationResult(
                score=None, label="SKIPPED", explanation="actual_output is missing"
            )
        import jsonschema

        instance = sample.actual_output
        if isinstance(instance, str):
            try:
                instance = json.loads(instance)
            except json.JSONDecodeError as exc:
                return EvaluationResult(
                    score=0.0,
                    label="FAIL",
                    explanation=f"actual_output is not valid JSON: {exc}",
                )
        try:
            jsonschema.validate(instance=instance, schema=self._schema)
        except jsonschema.ValidationError as exc:
            return EvaluationResult(
                score=0.0,
                label="FAIL",
                explanation=exc.message,
            )
        return EvaluationResult(
            score=1.0,
            label="PASS",
            explanation="schema validation passed",
        )


class LatencyEvaluator:
    name = "latency"

    def __init__(self, config: dict[str, Any]) -> None:
        max_ms = config.get("max_ms")
        if max_ms is None:
            raise ValueError("latency evaluator requires config.max_ms")
        self._max_ms = float(max_ms)

    async def evaluate(self, sample: EvaluationSample) -> EvaluationResult:
        ctx = _as_context(sample)
        latency = ctx.get("latency_ms")
        if latency is None:
            return EvaluationResult(
                score=None, label="SKIPPED", explanation="context.latency_ms is missing"
            )
        value = float(latency)
        ok = value <= self._max_ms
        return EvaluationResult(
            score=1.0 if ok else 0.0,
            label="PASS" if ok else "FAIL",
            explanation=f"latency_ms={value} max_ms={self._max_ms}",
            metadata={"latency_ms": value, "max_ms": self._max_ms},
        )


class TokenUsageEvaluator:
    name = "token_usage"

    def __init__(self, config: dict[str, Any]) -> None:
        max_tokens = config.get("max_tokens")
        if max_tokens is None:
            raise ValueError("token_usage evaluator requires config.max_tokens")
        self._max_tokens = float(max_tokens)

    async def evaluate(self, sample: EvaluationSample) -> EvaluationResult:
        ctx = _as_context(sample)
        tokens = ctx.get("total_tokens")
        if tokens is None:
            return EvaluationResult(
                score=None,
                label="SKIPPED",
                explanation="context.total_tokens is missing",
            )
        value = float(tokens)
        ok = value <= self._max_tokens
        return EvaluationResult(
            score=1.0 if ok else 0.0,
            label="PASS" if ok else "FAIL",
            explanation=f"total_tokens={value} max_tokens={self._max_tokens}",
            metadata={"total_tokens": value, "max_tokens": self._max_tokens},
        )


class CostEvaluator:
    name = "cost"

    def __init__(self, config: dict[str, Any]) -> None:
        max_usd = config.get("max_usd")
        if max_usd is None:
            raise ValueError("cost evaluator requires config.max_usd")
        self._max_usd = float(max_usd)

    async def evaluate(self, sample: EvaluationSample) -> EvaluationResult:
        ctx = _as_context(sample)
        cost = ctx.get("cost_usd")
        if cost is None:
            return EvaluationResult(
                score=None, label="SKIPPED", explanation="context.cost_usd is missing"
            )
        value = float(cost)
        ok = value <= self._max_usd
        return EvaluationResult(
            score=1.0 if ok else 0.0,
            label="PASS" if ok else "FAIL",
            explanation=f"cost_usd={value} max_usd={self._max_usd}",
            metadata={"cost_usd": value, "max_usd": self._max_usd},
        )


def _retrieved_doc_ids(ctx: dict[str, Any]) -> list[str] | None:
    if "documents" in ctx:
        documents = ctx["documents"]
        if documents is None:
            return None
        if not isinstance(documents, list):
            return None
        ids: list[str] = []
        for doc in documents:
            if isinstance(doc, dict) and doc.get("id") is not None:
                ids.append(str(doc["id"]))
        return ids
    if "retrieved_doc_ids" in ctx:
        retrieved = ctx["retrieved_doc_ids"]
        if retrieved is None:
            return None
        if not isinstance(retrieved, list):
            return None
        return [str(doc_id) for doc_id in retrieved]
    return None


def _parse_k(kind: str, config: dict[str, Any], *, default: int = 5) -> int:
    k = config.get("k", default)
    k_int = int(k)
    if k_int < 1:
        raise ValueError(f"{kind} evaluator requires config.k >= 1")
    return k_int


def _retrieval_inputs(
    sample: EvaluationSample, *, k: int
) -> tuple[EvaluationResult | None, list[str] | None, list[str] | None, dict[str, Any]]:
    """Parse expected/retrieved ids for retrieval metrics.

    Returns ``(early_result, expected_list, top_k_ids, meta)``. When ``early_result``
    is set, scoring should stop.
    """
    expected = sample.metadata.get("expected_doc_ids")
    if expected is None:
        return skip("metadata.expected_doc_ids is missing"), None, None, {}
    if not isinstance(expected, list):
        return skip("metadata.expected_doc_ids must be a list"), None, None, {}
    if not expected:
        return skip("metadata.expected_doc_ids is empty"), None, None, {}

    ctx = _as_context(sample)
    retrieved = _retrieved_doc_ids(ctx)
    if retrieved is None:
        return (
            fail_min(
                "no documents retrieved (context.documents or context.retrieved_doc_ids is missing)"
            ),
            None,
            None,
            {},
        )
    if not retrieved:
        return (
            fail_min("retrieved documents are empty or have no document ids"),
            None,
            None,
            {},
        )

    top_k = retrieved[:k]
    meta = {
        "k": k,
        "expected_doc_ids": list(expected),
        "retrieved_top_k": list(top_k),
    }
    return None, [str(doc_id) for doc_id in expected], top_k, meta


class HitAtKEvaluator:
    name = "hit_at_k"

    def __init__(self, config: dict[str, Any]) -> None:
        self._k = _parse_k(self.name, config)

    async def evaluate(self, sample: EvaluationSample) -> EvaluationResult:
        early, expected, top_k, meta = _retrieval_inputs(sample, k=self._k)
        if early is not None:
            return early
        assert expected is not None and top_k is not None
        hit = bool(set(expected) & set(top_k))
        if hit:
            return pass_("expected doc in top-k retrieved", metadata=meta)
        return fail_min("no expected doc in top-k retrieved", metadata=meta)


class RecallAtKEvaluator:
    name = "recall_at_k"

    def __init__(self, config: dict[str, Any]) -> None:
        self._k = _parse_k(self.name, config)

    async def evaluate(self, sample: EvaluationSample) -> EvaluationResult:
        early, expected, top_k, meta = _retrieval_inputs(sample, k=self._k)
        if early is not None:
            return early
        assert expected is not None and top_k is not None
        expected_set = set(expected)
        hits = len(expected_set & set(top_k))
        score = hits / len(expected_set)
        meta = {**meta, "hits": hits, "n_expected": len(expected_set)}
        return EvaluationResult(
            score=score,
            label=None,
            explanation=f"{hits}/{len(expected_set)} expected docs in top-{self._k}",
            metadata=meta,
        )


class MRREvaluator:
    name = "mrr"

    def __init__(self, config: dict[str, Any]) -> None:
        self._k = _parse_k(self.name, config)

    async def evaluate(self, sample: EvaluationSample) -> EvaluationResult:
        early, expected, top_k, meta = _retrieval_inputs(sample, k=self._k)
        if early is not None:
            return early
        assert expected is not None and top_k is not None
        expected_set = set(expected)
        rank: int | None = None
        for i, doc_id in enumerate(top_k, start=1):
            if doc_id in expected_set:
                rank = i
                break
        score = 0.0 if rank is None else 1.0 / rank
        meta = {**meta, "rank": rank}
        return EvaluationResult(
            score=score,
            label=None,
            explanation=(
                f"first expected doc at rank {rank}"
                if rank is not None
                else "no expected doc in top-k"
            ),
            metadata=meta,
        )


class ToolCallSuccessEvaluator:
    name = "tool_call_success"

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config

    async def evaluate(self, sample: EvaluationSample) -> EvaluationResult:
        ctx = _as_context(sample)
        tool_calls = ctx.get("tool_calls")
        if tool_calls is None:
            return skip("context.tool_calls is missing")
        if not isinstance(tool_calls, list):
            return skip("context.tool_calls must be a list")
        if not tool_calls:
            return pass_("no tool calls", metadata={"tool_call_count": 0})
        failures = [
            call
            for call in tool_calls
            if not isinstance(call, dict) or call.get("success") is not True
        ]
        ok = len(failures) == 0
        meta = {"tool_call_count": len(tool_calls), "failures": len(failures)}
        if ok:
            return pass_("all tool calls succeeded", metadata=meta)
        return fail_min("one or more tool calls failed", metadata=meta)


class MustContainEvaluator:
    name = "must_contain"

    def __init__(self, config: dict[str, Any]) -> None:
        self._case_sensitive = bool(config.get("case_sensitive", False))

    async def evaluate(self, sample: EvaluationSample) -> EvaluationResult:
        if sample.actual_output is None:
            return EvaluationResult(
                score=None, label="SKIPPED", explanation="actual_output is missing"
            )
        raw = sample.metadata.get("must_contain")
        if raw is None:
            return EvaluationResult(
                score=None,
                label="SKIPPED",
                explanation="metadata.must_contain is missing",
            )
        if not isinstance(raw, list) or not raw:
            return EvaluationResult(
                score=None,
                label="SKIPPED",
                explanation="metadata.must_contain must be a non-empty list",
            )
        keywords = [str(x).strip() for x in raw if str(x).strip()]
        if not keywords:
            return EvaluationResult(
                score=None,
                label="SKIPPED",
                explanation="metadata.must_contain must be a non-empty list",
            )

        haystack = _stringify(sample.actual_output)
        needles = keywords
        if not self._case_sensitive:
            haystack = haystack.lower()
            needles = [k.lower() for k in keywords]
        missing = [keywords[i] for i, needle in enumerate(needles) if needle not in haystack]
        ok = len(missing) == 0
        return EvaluationResult(
            score=1.0 if ok else 0.0,
            label="PASS" if ok else "FAIL",
            explanation=("all required phrases found" if ok else f"missing: {', '.join(missing)}"),
            metadata={
                "must_contain": keywords,
                "missing": missing,
                "case_sensitive": self._case_sensitive,
            },
        )


def register_deterministic_evaluators() -> None:
    register_evaluator("exact_match", ExactMatchEvaluator)
    register_evaluator("contains", ContainsEvaluator)
    register_evaluator("regex", RegexEvaluator)
    register_evaluator("json_schema", JsonSchemaEvaluator)
    register_evaluator("latency", LatencyEvaluator)
    register_evaluator("token_usage", TokenUsageEvaluator)
    register_evaluator("cost", CostEvaluator)
    register_evaluator("tool_call_success", ToolCallSuccessEvaluator)
    register_evaluator("hit_at_k", HitAtKEvaluator)
    register_evaluator("recall_at_k", RecallAtKEvaluator)
    register_evaluator("mrr", MRREvaluator)
    register_evaluator("must_contain", MustContainEvaluator)

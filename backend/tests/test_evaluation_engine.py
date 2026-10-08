from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest

from aiobs.config import get_settings
from aiobs.domain.dataset import DatasetItem
from aiobs.domain.evaluation import EvaluationRun
from aiobs.domain.evaluator import Evaluator
from aiobs.domain.trace import Span, Trace
from aiobs.evaluation.deterministic import (
    ContainsEvaluator,
    CostEvaluator,
    ExactMatchEvaluator,
    JsonSchemaEvaluator,
    LatencyEvaluator,
    RegexEvaluator,
    TokenUsageEvaluator,
    ToolCallSuccessEvaluator,
    register_deterministic_evaluators,
)
from aiobs.evaluation.llm_judges import LlmJudgeEvaluator
from aiobs.evaluation.protocol import EvaluationSample
from aiobs.evaluation.registry import clear_registry, create_evaluator, list_registered_kinds
from aiobs.evaluation.runner import EvaluationRunner
from aiobs.evaluation.trace_context import build_eval_context_from_trace


@pytest.fixture(autouse=True)
def _registry() -> None:
    clear_registry()
    register_deterministic_evaluators()
    yield
    clear_registry()


def _sample(**kwargs):
    defaults = {
        "input": "q",
        "expected_output": "hello",
        "actual_output": "hello",
        "context": None,
        "metadata": {},
    }
    defaults.update(kwargs)
    return EvaluationSample(**defaults)


@pytest.mark.asyncio
async def test_exact_match_pass_fail() -> None:
    ev = ExactMatchEvaluator({})
    ok = await ev.evaluate(_sample())
    assert ok.score == 1.0
    bad = await ev.evaluate(_sample(actual_output="bye"))
    assert bad.score == 0.0


@pytest.mark.asyncio
async def test_contains_and_regex() -> None:
    contains = ContainsEvaluator({"substring": "ell"})
    assert (await contains.evaluate(_sample())).score == 1.0
    regex = RegexEvaluator({"pattern": r"^he"})
    assert (await regex.evaluate(_sample())).score == 1.0


@pytest.mark.asyncio
async def test_json_schema() -> None:
    ev = JsonSchemaEvaluator({"schema": {"type": "object", "required": ["a"]}})
    ok = await ev.evaluate(_sample(actual_output={"a": 1}))
    assert ok.score == 1.0
    bad = await ev.evaluate(_sample(actual_output={"b": 1}))
    assert bad.score == 0.0


@pytest.mark.asyncio
async def test_latency_token_cost_tools() -> None:
    latency = LatencyEvaluator({"max_ms": 100})
    assert (
        await latency.evaluate(_sample(actual_output=None, context={"latency_ms": 50}))
    ).score == 1.0
    tokens = TokenUsageEvaluator({"max_tokens": 10})
    assert (
        await tokens.evaluate(_sample(actual_output=None, context={"total_tokens": 5}))
    ).score == 1.0
    cost = CostEvaluator({"max_usd": 0.01})
    assert (
        await cost.evaluate(_sample(actual_output=None, context={"cost_usd": 0.005}))
    ).score == 1.0
    tools = ToolCallSuccessEvaluator({})
    result = await tools.evaluate(
        _sample(
            actual_output=None,
            context={"tool_calls": [{"name": "search", "success": True}]},
        )
    )
    assert result.score == 1.0


@pytest.mark.asyncio
async def test_skipped_without_actual() -> None:
    ev = ExactMatchEvaluator({})
    result = await ev.evaluate(_sample(actual_output=None))
    assert result.label == "SKIPPED"
    assert result.score is None


@pytest.mark.asyncio
async def test_llm_judge_with_mock() -> None:
    class FakeLlm:
        async def complete_json(self, *, system: str, user: str, model: str | None = None):
            return {"score": 0.9, "label": "PASS", "explanation": "good"}

    judge = LlmJudgeEvaluator("correctness", {}, FakeLlm(), default_model=get_settings().llm_model)
    result = await judge.evaluate(_sample())
    assert result.score == 0.9
    assert result.metadata["prompt_version"] == "correctness.v2"
    assert result.metadata["model"] == get_settings().llm_model


@pytest.mark.asyncio
async def test_runner_hit_at_k_scores_without_actual_output() -> None:
    entity = Evaluator.create(
        uuid.uuid4(), "hit_at_k", "deterministic", {"kind": "hit_at_k", "k": 2}
    )
    item = DatasetItem.create(
        uuid.uuid4(),
        input="q",
        expected_output="gold",
        actual_output=None,
        context={"documents": [{"id": "doc-a"}, {"id": "doc-b"}]},
        metadata={"expected_doc_ids": ["doc-a"]},
    )
    runner = EvaluationRunner()
    run = EvaluationRun.create(uuid.uuid4(), entity.id)
    finished, results = await runner.run_evaluator(run=run, evaluator_entity=entity, items=[item])
    assert results[0].label == "PASS"
    assert results[0].score == 1.0
    assert results[0].explanation != "actual_output is missing"
    assert finished.status == "PASSED"


@pytest.mark.asyncio
async def test_runner_maps_errors_not_to_zero() -> None:
    class Boom:
        name = "boom"

        async def evaluate(self, sample):
            raise RuntimeError("provider down")

    entity = Evaluator.create(uuid.uuid4(), "boom", "deterministic", {"kind": "exact_match"})
    item = DatasetItem.create(uuid.uuid4(), input="x", expected_output="y", actual_output="y")
    runner = EvaluationRunner(resolve_evaluator=lambda _e: Boom())
    run = EvaluationRun.create(uuid.uuid4(), entity.id)
    finished, results = await runner.run_evaluator(run=run, evaluator_entity=entity, items=[item])
    assert finished.status == "ERROR"
    assert results[0].score is None
    assert results[0].label == "ERROR"


@pytest.mark.asyncio
async def test_runner_pass_threshold_fails_below_and_passes_at_or_above() -> None:
    class Partial:
        name = "partial"

        def __init__(self, score: float) -> None:
            self._score = score

        async def evaluate(self, sample):
            from aiobs.evaluation.protocol import EvaluationResult

            return EvaluationResult(
                score=self._score,
                label="PASS" if self._score >= 0.7 else "FAIL",
                explanation="partial",
                metadata={},
            )

    entity = Evaluator.create(uuid.uuid4(), "partial", "llm_judge", {"kind": "correctness"})
    item = DatasetItem.create(uuid.uuid4(), input="x", expected_output="y", actual_output="y")
    runner_fail = EvaluationRunner(resolve_evaluator=lambda _e: Partial(0.6))
    run_fail = EvaluationRun.create(uuid.uuid4(), entity.id)
    finished_fail, _ = await runner_fail.run_evaluator(
        run=run_fail, evaluator_entity=entity, items=[item], pass_threshold=0.7
    )
    assert finished_fail.status == "FAILED"

    runner_pass = EvaluationRunner(resolve_evaluator=lambda _e: Partial(0.7))
    run_pass = EvaluationRun.create(uuid.uuid4(), entity.id)
    finished_pass, _ = await runner_pass.run_evaluator(
        run=run_pass, evaluator_entity=entity, items=[item], pass_threshold=0.7
    )
    assert finished_pass.status == "PASSED"


@pytest.mark.asyncio
async def test_runner_without_threshold_fails_on_fail_label() -> None:
    class Partial:
        name = "partial"

        async def evaluate(self, sample):
            from aiobs.evaluation.protocol import EvaluationResult

            return EvaluationResult(score=0.6, label="FAIL", explanation="ok", metadata={})

    entity = Evaluator.create(uuid.uuid4(), "partial", "llm_judge", {"kind": "correctness"})
    item = DatasetItem.create(uuid.uuid4(), input="x", expected_output="y", actual_output="y")
    runner = EvaluationRunner(resolve_evaluator=lambda _e: Partial())
    run = EvaluationRun.create(uuid.uuid4(), entity.id)
    finished, _ = await runner.run_evaluator(run=run, evaluator_entity=entity, items=[item])
    assert finished.status == "FAILED"


@pytest.mark.asyncio
async def test_runner_fail_label_above_threshold_fails() -> None:
    class Judge:
        name = "judge"

        async def evaluate(self, sample):
            from aiobs.evaluation.protocol import EvaluationResult

            return EvaluationResult(score=0.9, label="FAIL", explanation="x", metadata={})

    entity = Evaluator.create(uuid.uuid4(), "judge", "llm_judge", {"kind": "correctness"})
    item = DatasetItem.create(uuid.uuid4(), input="x", expected_output="y", actual_output="y")
    runner = EvaluationRunner(resolve_evaluator=lambda _e: Judge())
    finished, results = await runner.run_evaluator(
        run=EvaluationRun.create(uuid.uuid4(), entity.id),
        evaluator_entity=entity,
        items=[item],
        pass_threshold=0.7,
    )
    assert finished.status == "FAILED"
    assert results[0].label == "FAIL"


@pytest.mark.asyncio
async def test_runner_rewrites_pass_label_below_threshold() -> None:
    class Judge:
        name = "judge"

        async def evaluate(self, sample):
            from aiobs.evaluation.protocol import EvaluationResult

            return EvaluationResult(score=0.5, label="PASS", explanation="x", metadata={"m": 1})

    entity = Evaluator.create(uuid.uuid4(), "judge", "llm_judge", {"kind": "correctness"})
    item = DatasetItem.create(uuid.uuid4(), input="x", expected_output="y", actual_output="y")
    runner = EvaluationRunner(resolve_evaluator=lambda _e: Judge())
    finished, results = await runner.run_evaluator(
        run=EvaluationRun.create(uuid.uuid4(), entity.id),
        evaluator_entity=entity,
        items=[item],
        pass_threshold=0.7,
    )
    assert finished.status == "FAILED"
    # Stored label is the effective verdict so pass_rate agrees with the run status.
    assert results[0].label == "FAIL"
    assert results[0].metadata["judge_label"] == "PASS"
    assert results[0].metadata["m"] == 1


@pytest.mark.asyncio
async def test_runner_config_override_wins_over_entity_config() -> None:
    entity = Evaluator.create(
        uuid.uuid4(), "hit_at_k", "deterministic", {"kind": "hit_at_k", "k": 5}
    )
    item = DatasetItem.create(
        uuid.uuid4(),
        input="q",
        expected_output="gold",
        context={"documents": [{"id": "other"}, {"id": "target"}]},
        metadata={"expected_doc_ids": ["target"]},
    )
    runner = EvaluationRunner()

    base_run, base_results = await runner.run_evaluator(
        run=EvaluationRun.create(uuid.uuid4(), entity.id), evaluator_entity=entity, items=[item]
    )
    assert base_results[0].label == "PASS"

    over_run, over_results = await runner.run_evaluator(
        run=EvaluationRun.create(uuid.uuid4(), entity.id),
        evaluator_entity=entity,
        items=[item],
        config_override={"k": 1, "kind": "exact_match"},
    )
    assert over_results[0].label == "FAIL"
    assert over_results[0].metadata["k"] == 1
    # kind cannot be overridden; hash reflects effective config
    assert over_run.metadata["evaluator_kind"] == "hit_at_k"
    assert over_run.metadata["config_hash"] != base_run.metadata["config_hash"]
    assert over_run.metadata["config_override"] == {"k": 1}


@pytest.mark.asyncio
async def test_runner_missing_output_items_fail_for_every_kind() -> None:
    entity = Evaluator.create(
        uuid.uuid4(), "hit_at_k", "deterministic", {"kind": "hit_at_k", "k": 5}
    )
    present = DatasetItem.create(
        uuid.uuid4(),
        input="q",
        context={"documents": [{"id": "target"}]},
        metadata={"expected_doc_ids": ["target"]},
    )
    missing = DatasetItem.create(
        uuid.uuid4(), input="q2", metadata={"expected_doc_ids": ["target"]}
    )
    runner = EvaluationRunner()
    finished, results = await runner.run_evaluator(
        run=EvaluationRun.create(uuid.uuid4(), entity.id),
        evaluator_entity=entity,
        items=[present, missing],
        missing_output_item_ids={missing.id},
    )
    by_item = {r.dataset_item_id: r for r in results}
    assert by_item[present.id].label == "PASS"
    assert by_item[missing.id].label == "FAIL"
    assert by_item[missing.id].score == 0.0
    assert "no output" in (by_item[missing.id].explanation or "")
    assert finished.status == "FAILED"


def test_registry_lists_kinds() -> None:
    assert "exact_match" in list_registered_kinds()
    create_evaluator("exact_match", {})


def test_build_eval_context_from_trace() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 1, 0, 0, 1, tzinfo=UTC)
    span = Span(
        id=uuid.uuid4(),
        span_id="a" * 16,
        parent_span_id=None,
        name="tool_search",
        kind="TOOL",
        start_time=start,
        end_time=end,
        status="ok",
        attributes={
            "gen_ai.usage.total_tokens": 42,
            "gen_ai.usage.cost": 0.002,
        },
    )
    trace = Trace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        trace_id="b" * 32,
        name="t",
        status="ok",
        start_time=start,
        end_time=end,
        spans=(span,),
    )
    ctx = build_eval_context_from_trace(trace)
    assert ctx["latency_ms"] == 1000.0
    assert ctx["total_tokens"] == 42
    assert ctx["cost_usd"] == 0.002
    assert ctx["tool_calls"][0]["success"] is True


def test_build_eval_context_ignores_non_tool_span_named_tool() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 1, 0, 0, 1, tzinfo=UTC)
    span = Span(
        id=uuid.uuid4(),
        span_id="a" * 16,
        parent_span_id=None,
        name="toolbox_lookup",
        kind="CHAIN",
        start_time=start,
        end_time=end,
        status="error",
        attributes={},
    )
    trace = Trace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        trace_id="b" * 32,
        name="t",
        status="ok",
        start_time=start,
        end_time=end,
        spans=(span,),
    )
    assert "tool_calls" not in build_eval_context_from_trace(trace)


def test_build_eval_context_includes_retrieval_documents() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 1, 0, 0, 1, tzinfo=UTC)
    retriever = Span(
        id=uuid.uuid4(),
        span_id="c" * 16,
        parent_span_id=None,
        name="retrieve",
        kind="RETRIEVER",
        start_time=start,
        end_time=end,
        status="ok",
        attributes={
            "retrieval.documents": [
                {"id": "doc-1", "title": "PTO", "text": "20 days paid time off."},
                {"id": "doc-2", "title": "Holidays"},
            ],
        },
    )
    json_span = Span(
        id=uuid.uuid4(),
        span_id="d" * 16,
        parent_span_id=None,
        name="retrieve_json",
        kind="RETRIEVER",
        start_time=start,
        end_time=end,
        status="ok",
        attributes={
            "retrieval.documents": json.dumps([{"id": "doc-3", "text": "Remote work policy."}]),
        },
    )
    trace = Trace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        trace_id="e" * 32,
        name="rag",
        status="ok",
        start_time=start,
        end_time=end,
        spans=(retriever, json_span),
    )
    ctx = build_eval_context_from_trace(trace)
    # Same end_time: the later span in trace order is the final retrieval stage.
    assert ctx["documents"] == [{"id": "doc-3", "text": "Remote work policy."}]


def test_build_eval_context_uses_last_retrieval_stage() -> None:
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    t1 = datetime(2024, 1, 1, 0, 0, 1, tzinfo=UTC)
    t2 = datetime(2024, 1, 1, 0, 0, 2, tzinfo=UTC)
    rerank = Span(
        id=uuid.uuid4(),
        span_id="f" * 16,
        parent_span_id=None,
        name="rerank",
        kind="RERANKER",
        start_time=t1,
        end_time=t2,
        status="ok",
        attributes={
            "reranker.output_documents": [
                {"id": "doc-7"},
                {"id": "doc-2"},
                {"id": "doc-7"},
            ],
        },
    )
    retrieve = Span(
        id=uuid.uuid4(),
        span_id="c" * 16,
        parent_span_id=None,
        name="retrieve",
        kind="RETRIEVER",
        start_time=t0,
        end_time=t1,
        status="ok",
        attributes={
            "retrieval.documents": [{"id": f"doc-{i}"} for i in range(1, 21)],
        },
    )
    trace = Trace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        trace_id="e" * 32,
        name="rag",
        status="ok",
        start_time=t0,
        end_time=t2,
        # Span order in the trace must not matter: end_time decides.
        spans=(rerank, retrieve),
    )
    ctx = build_eval_context_from_trace(trace)
    assert ctx["documents"] == [{"id": "doc-7"}, {"id": "doc-2"}]


def test_build_eval_context_empty_retrieval_sets_documents_list() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 1, 0, 0, 1, tzinfo=UTC)
    retriever = Span(
        id=uuid.uuid4(),
        span_id="c" * 16,
        parent_span_id=None,
        name="retrieve",
        kind="RETRIEVER",
        start_time=start,
        end_time=end,
        status="error",
        attributes={"retrieval.document_count": 0},
    )
    trace = Trace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        trace_id="e" * 32,
        name="rag",
        status="ok",
        start_time=start,
        end_time=end,
        spans=(retriever,),
    )
    ctx = build_eval_context_from_trace(trace)
    assert ctx["documents"] == []


@pytest.mark.asyncio
async def test_tool_call_success_non_list_skipped() -> None:
    tools = ToolCallSuccessEvaluator({})
    result = await tools.evaluate(
        _sample(actual_output=None, context={"tool_calls": {"name": "search"}})
    )
    assert result.label == "SKIPPED"
    assert result.score is None
    assert result.explanation == "context.tool_calls must be a list"


@pytest.mark.asyncio
async def test_groundedness_empty_documents_fail_min() -> None:
    class FakeLlm:
        async def complete_json(self, *, system: str, user: str, model: str | None = None):
            raise AssertionError("judge should not be called when documents are empty")

    judge = LlmJudgeEvaluator("groundedness", {}, FakeLlm(), default_model=get_settings().llm_model)
    result = await judge.evaluate(
        _sample(context={"documents": []}),
    )
    assert result.label == "FAIL"
    assert result.score == 0.0
    assert result.explanation == "context.documents are missing or empty"


@pytest.mark.asyncio
async def test_groundedness_missing_documents_fail_min() -> None:
    class FakeLlm:
        async def complete_json(self, *, system: str, user: str, model: str | None = None):
            raise AssertionError("judge should not be called when documents are missing")

    judge = LlmJudgeEvaluator("groundedness", {}, FakeLlm(), default_model=get_settings().llm_model)
    result = await judge.evaluate(_sample(context={"latency_ms": 10}))
    assert result.label == "FAIL"
    assert result.score == 0.0


@pytest.mark.asyncio
async def test_groundedness_context_none_skipped() -> None:
    class FakeLlm:
        async def complete_json(self, *, system: str, user: str, model: str | None = None):
            raise AssertionError("judge should not be called when context is missing")

    judge = LlmJudgeEvaluator("groundedness", {}, FakeLlm(), default_model=get_settings().llm_model)
    result = await judge.evaluate(_sample(context=None))
    assert result.label == "SKIPPED"
    assert result.score is None


@pytest.mark.asyncio
async def test_groundedness_judge_payload_includes_document_texts() -> None:
    captured: dict[str, str] = {}

    class FakeLlm:
        async def complete_json(self, *, system: str, user: str, model: str | None = None):
            captured["user"] = user
            return {"score": 1.0, "label": "PASS", "explanation": "grounded"}

    judge = LlmJudgeEvaluator("groundedness", {}, FakeLlm(), default_model=get_settings().llm_model)
    await judge.evaluate(
        _sample(
            context={
                "documents": [
                    {"id": "doc-1", "text": "Policy excerpt for the judge."},
                ],
            },
        )
    )
    payload = json.loads(captured["user"])
    assert payload["context"]["documents"][0]["text"] == "Policy excerpt for the judge."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "expected_keys"),
    [
        ("answer_relevance", {"input", "actual_output"}),
        ("groundedness", {"input", "actual_output", "context"}),
        ("correctness", {"input", "expected_output", "actual_output"}),
    ],
)
async def test_judge_payload_never_leaks_gold(kind: str, expected_keys: set[str]) -> None:
    captured: dict[str, str] = {}

    class FakeLlm:
        async def complete_json(self, *, system: str, user: str, model: str | None = None):
            captured["user"] = user
            return {"score": 1.0, "label": "PASS", "explanation": "ok"}

    judge = LlmJudgeEvaluator(kind, {}, FakeLlm(), default_model=get_settings().llm_model)
    await judge.evaluate(
        EvaluationSample(
            input="q",
            expected_output="GOLD-ANSWER",
            actual_output="answer",
            context={"documents": [{"id": "doc-1", "text": "t"}], "latency_ms": 12},
            metadata={"expected_doc_ids": ["GOLD-DOC"]},
        )
    )
    payload = json.loads(captured["user"])
    assert set(payload) == expected_keys
    assert "GOLD-DOC" not in captured["user"]
    if kind != "correctness":
        assert "GOLD-ANSWER" not in captured["user"]
    if kind == "groundedness":
        # Only documents reach the judge, not timing/cost context.
        assert payload["context"] == {"documents": [{"id": "doc-1", "text": "t"}]}


def test_build_eval_context_skips_stage_without_recorded_documents() -> None:
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    t1 = datetime(2024, 1, 1, 0, 0, 1, tzinfo=UTC)
    retrieve = Span(
        id=uuid.uuid4(),
        span_id="c" * 16,
        parent_span_id=None,
        name="retrieve",
        kind="RETRIEVER",
        start_time=t0,
        end_time=t0,
        status="ok",
        attributes={"retrieval.documents": [{"id": "doc-1"}]},
    )
    uninstrumented_rerank = Span(
        id=uuid.uuid4(),
        span_id="f" * 16,
        parent_span_id=None,
        name="rerank",
        kind="RERANKER",
        start_time=t0,
        end_time=t1,
        status="ok",
        attributes={},
    )
    trace = Trace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        trace_id="e" * 32,
        name="rag",
        status="ok",
        start_time=t0,
        end_time=t1,
        spans=(retrieve, uninstrumented_rerank),
    )
    assert build_eval_context_from_trace(trace)["documents"] == [{"id": "doc-1"}]

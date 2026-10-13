from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import Iterator
from typing import Any

import httpx2
import pytest

import aiobs
from aiobs import Client, _context
from aiobs.experiment import _output_entry

PROJECT_ID = str(uuid.uuid4())


class FakeServer:
    """Just enough of the platform API for the experiment loop."""

    def __init__(self) -> None:
        self.datasets: dict[str, dict[str, Any]] = {}
        self.items: dict[str, list[dict[str, Any]]] = {}
        self.experiments: dict[str, dict[str, Any]] = {}
        self.outputs: dict[str, dict[str, dict[str, Any]]] = {}
        self.metrics_sets: dict[str, dict[str, Any]] = {}
        self.client_results: dict[str, list[dict[str, Any]]] = {}
        self.scored_on_server: set[str] = set()
        self.reject_client_results = False
        self.calls: list[tuple[str, str, Any]] = []
        self.add_metrics_set(
            "Default",
            default=True,
            entries=[
                {"kind": "hit_at_k", "enabled": True, "threshold": 0.8, "config": {"k": 5}},
                {"kind": "groundedness", "enabled": True, "threshold": 0.7, "config": {}},
            ],
        )

    def add_metrics_set(
        self, name: str, *, entries: list[dict[str, Any]], default: bool = False
    ) -> dict[str, Any]:
        ms = {
            "id": str(uuid.uuid4()),
            "project_id": PROJECT_ID,
            "name": name,
            "version": 1,
            "is_project_default": default,
            "entries": entries,
        }
        self.metrics_sets[ms["id"]] = ms
        return ms

    def add_dataset(self, name: str, rows: list[dict[str, Any]]) -> str:
        ds_id = str(uuid.uuid4())
        self.datasets[ds_id] = {
            "id": ds_id,
            "project_id": PROJECT_ID,
            "name": name,
            "version": 1,
        }
        self.items[ds_id] = [{"id": str(uuid.uuid4()), "dataset_id": ds_id, **r} for r in rows]
        return ds_id

    def add_experiment(self, name: str, dataset_id: str, created_at: str) -> str:
        exp_id = str(uuid.uuid4())
        self.experiments[exp_id] = {
            "id": exp_id,
            "project_id": PROJECT_ID,
            "name": name,
            "dataset_id": dataset_id,
            "status": "completed",
            "created_at": created_at,
        }
        return exp_id

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        method, path = request.method, request.url.path
        body = json.loads(request.content) if request.content else None
        self.calls.append((method, path, body))

        if m := re.fullmatch(r"/api/v1/projects/[^/]+/datasets", path):
            if method == "GET":
                return httpx2.Response(200, json=list(self.datasets.values()))
            ds_id = self.add_dataset(body["name"], [])
            return httpx2.Response(201, json=self.datasets[ds_id])
        if m := re.fullmatch(r"/api/v1/datasets/([^/]+)/items", path):
            item = {"id": str(uuid.uuid4()), "dataset_id": m[1], **body}
            self.items[m[1]].append(item)
            return httpx2.Response(201, json=item)
        if m := re.fullmatch(r"/api/v1/datasets/([^/]+)", path):
            return httpx2.Response(200, json={**self.datasets[m[1]], "items": self.items[m[1]]})
        if re.fullmatch(r"/api/v1/projects/[^/]+/metrics-sets", path):
            if method == "GET":
                return httpx2.Response(200, json=list(self.metrics_sets.values()))
            return httpx2.Response(
                201, json=self.add_metrics_set(body["name"], entries=body["entries"])
            )
        if m := re.fullmatch(r"/api/v1/metrics-sets/([^/]+)", path):
            return httpx2.Response(200, json=self.metrics_sets[m[1]])
        if re.fullmatch(r"/api/v1/projects/[^/]+/experiments", path):
            if method == "GET":
                return httpx2.Response(200, json=list(self.experiments.values()))
            exp_id = str(uuid.uuid4())
            self.experiments[exp_id] = {
                "id": exp_id,
                "project_id": PROJECT_ID,
                "status": "pending",
                **body,
            }
            self.outputs[exp_id] = {}
            return httpx2.Response(201, json=self.experiments[exp_id])
        if m := re.fullmatch(r"/api/v1/experiments/([^/]+)/outputs", path):
            store = self.outputs[m[1]]
            if method == "PUT":
                for entry in body["items"]:
                    current = store.setdefault(
                        entry["dataset_item_id"],
                        {"dataset_item_id": entry["dataset_item_id"], "metadata": {}},
                    )
                    current.update(entry)
                return httpx2.Response(200, json={"upserted": len(body["items"]), "items": []})
            return httpx2.Response(200, json=list(store.values()))
        if m := re.fullmatch(r"/api/v1/experiments/([^/]+)/evaluate-pack", path):
            self.experiments[m[1]]["status"] = "completed"
            self.scored_on_server.add(m[1])
            return httpx2.Response(202, json=self.experiments[m[1]])
        if m := re.fullmatch(r"/api/v1/experiments/([^/]+)/client-results", path):
            if self.reject_client_results:
                return httpx2.Response(409, json={"detail": "name used by server evaluator"})
            self.client_results.setdefault(m[1], []).extend(body["metrics"])
            return httpx2.Response(201, json=[])
        if m := re.fullmatch(r"/api/v1/experiments/([^/]+)/runs", path):
            return httpx2.Response(200, json=[])
        if m := re.fullmatch(r"/api/v1/experiments/([^/]+)/summary", path):
            rows = []
            if m[1] in self.scored_on_server:
                rows.append({"evaluator_name": "hit_at_k", "mean_score": 0.5, "pass_rate": 0.5})
            for metric in self.client_results.get(m[1], []):
                scores = [r["score"] for r in metric["results"] if r.get("score") is not None]
                mean = sum(scores) / len(scores) if scores else None
                rows.append({"evaluator_name": metric["name"], "mean_score": mean})
            return httpx2.Response(200, json={"experiment_id": m[1], "evaluators": rows})
        if m := re.fullmatch(r"/api/v1/experiments/([^/]+)/compare/([^/]+)", path):
            return httpx2.Response(
                200,
                json={
                    "metrics": [
                        {"evaluator_name": "hit_at_k", "delta": -0.25, "status": "regressed"},
                    ]
                },
            )
        if m := re.fullmatch(r"/api/v1/experiments/([^/]+)", path):
            return httpx2.Response(200, json=self.experiments[m[1]])
        return httpx2.Response(404, json={"detail": f"unhandled {method} {path}"})


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeServer]:
    fake = FakeServer()
    client = Client("http://test", transport=httpx2.MockTransport(fake.handler))
    _context._reset_for_tests()
    monkeypatch.setattr(_context, "_CLIENT", client)
    monkeypatch.setenv("AIOBS_PROJECT_ID", PROJECT_ID)
    monkeypatch.delenv("AIOBS_UI_URL", raising=False)
    yield fake
    _context._reset_for_tests()


ROWS = [
    {"input": "q1", "expected_output": "a1", "expected_doc_ids": ["d1"]},
    {"input": "q2", "expected_output": "a2", "expected_doc_ids": ["d2"]},
]


def _task(item: Any) -> str:
    aiobs.set_retrieval_documents([{"id": "d1", "text": "doc"}])
    return f"answer to {item.input}"


def test_evaluate_inline_rows_writes_outputs_and_scores(server: FakeServer) -> None:
    def exact(item: Any, output: Any) -> bool:
        return output == f"answer to {item.input}"

    result = aiobs.evaluate(
        dataset=ROWS,
        task=_task,
        metrics=["hit_at_k", exact],
        name="v2",
        params={"model": "gemma4"},
    )

    (ds,) = server.datasets.values()
    assert ds["name"].startswith("inline-")
    stored_items = server.items[ds["id"]]
    assert stored_items[0]["metadata"] == {"expected_doc_ids": ["d1"]}

    exp = server.experiments[result.id]
    assert exp["model_config"] == {"model": "gemma4"}
    ms = server.metrics_sets[exp["metrics_set_id"]]
    assert ms["entries"] == [
        {"kind": "hit_at_k", "enabled": True, "threshold": 0.8, "config": {"k": 5}}
    ]

    outputs = server.outputs[result.id]
    assert len(outputs) == 2
    first = outputs[stored_items[0]["id"]]
    assert first["actual_output"] == "answer to q1"
    assert first["context"]["documents"] == [{"id": "d1", "text": "doc"}]
    assert "latency_ms" in first["context"]
    assert "client_metrics" not in first["metadata"]

    (submitted,) = server.client_results[result.id]
    assert submitted["name"] == "exact"
    assert "threshold" not in submitted
    assert sorted(r["score"] for r in submitted["results"]) == [1.0, 1.0]

    assert result.metrics == {"hit_at_k": 0.5, "exact": 1.0}
    assert result.url == f"http://test/experiments/{result.id}?project={PROJECT_ID}"
    text = result.summary()
    assert "hit_at_k" in text and "exact" in text and "local only" not in text


def test_evaluate_reuses_inline_dataset_and_metrics_set(server: FakeServer) -> None:
    aiobs.evaluate(dataset=ROWS, task=_task, metrics=["hit_at_k"], name="a")
    aiobs.evaluate(dataset=ROWS, task=_task, metrics=["hit_at_k"], name="b")
    assert len(server.datasets) == 1
    assert len(server.metrics_sets) == 2  # default + one sdk set


def test_evaluate_by_dataset_name_with_baseline_by_name(server: FakeServer) -> None:
    ds_id = server.add_dataset("gold-v1", [{"input": "q1"}])
    server.add_experiment("prod", ds_id, "2026-01-01T00:00:00Z")
    newest = server.add_experiment("prod", ds_id, "2026-02-01T00:00:00Z")

    result = aiobs.evaluate(
        dataset="gold-v1", task=lambda item: "x", baseline="prod", max_concurrency=4
    )

    assert server.experiments[result.id]["dataset_id"] == ds_id
    assert server.experiments[result.id]["baseline_experiment_id"] == newest
    assert result.baseline_id == newest
    assert result.comparison is not None
    assert "-0.250 regressed" in result.summary()


def test_metrics_none_uses_project_default_pack(server: FakeServer) -> None:
    aiobs.evaluate(dataset=ROWS, task=_task)
    pack_calls = [c for c in server.calls if c[1].endswith("/evaluate-pack")]
    assert pack_calls and pack_calls[0][2] is None


def test_local_only_metrics_skip_server_scoring(server: FakeServer) -> None:
    result = aiobs.evaluate(dataset=ROWS, task=_task, metrics=[lambda item, out: 0.5])
    assert not [c for c in server.calls if c[1].endswith("/evaluate-pack")]
    assert result.metrics == {"metric_0": 0.5}


def test_local_metric_options_and_failures_are_submitted(server: FakeServer) -> None:
    def flaky_task(item: Any) -> str:
        if item.input == "q2":
            raise RuntimeError("boom")
        return "ok"

    def broken(item: Any, output: Any) -> float:
        raise ValueError("bad metric")

    aiobs.evaluate(
        dataset=ROWS + [{"input": "q3"}],
        task=lambda item: flaky_task(item),
        metrics=[
            aiobs.LocalMetric(
                lambda item, out: 0.7, name="quality", threshold=0.5, config={"version": 2}
            ),
            broken,
        ],
    )
    (exp_id,) = server.client_results
    quality, broken_metric = server.client_results[exp_id]
    assert quality["name"] == "quality"
    assert quality["threshold"] == 0.5
    assert quality["config"] == {"version": 2}
    by_label = sorted((str(r.get("label")), r.get("score")) for r in quality["results"])
    assert by_label == [("FAIL", 0.0), ("None", 0.7), ("None", 0.7)]
    labels = sorted(str(r.get("label")) for r in broken_metric["results"])
    assert labels == ["ERROR", "ERROR", "FAIL"]


def test_rejected_client_results_fall_back_to_local_means(server: FakeServer) -> None:
    server.reject_client_results = True
    result = aiobs.evaluate(dataset=ROWS, task=_task, metrics=[lambda item, out: 0.5])
    assert result.metrics == {"metric_0": 0.5}
    assert "metric_0 (local only)" in result.summary()


def test_duplicate_local_metric_names_rejected(server: FakeServer) -> None:
    def m(item: Any, out: Any) -> float:
        return 1.0

    with pytest.raises(ValueError, match="duplicate local metric"):
        aiobs.evaluate(dataset=ROWS, task=_task, metrics=[m, aiobs.LocalMetric(m)])


def test_task_errors_are_recorded_not_raised(server: FakeServer) -> None:
    def flaky(item: Any) -> str:
        if item.input == "q2":
            raise RuntimeError("boom")
        return "ok"

    result = aiobs.evaluate(dataset=ROWS, task=flaky, metrics=["hit_at_k"])
    assert [r.error for r in result.errors] == ["RuntimeError: boom"]
    errored = next(o for o in server.outputs[result.id].values() if "error" in o["metadata"])
    assert "actual_output" not in errored

    with pytest.raises(RuntimeError, match="boom"):
        aiobs.evaluate(dataset=ROWS, task=flaky, metrics=["hit_at_k"], raise_on_error=True)


def test_start_experiment_context_manager(server: FakeServer) -> None:
    with aiobs.start_experiment("v2", dataset=ROWS, metrics=["hit_at_k"]) as exp:
        for item in exp.items():
            with exp.run(item):
                aiobs.set_output(f"via set_output {item.input}")

    assert exp.result is not None
    outputs = server.outputs[exp.id].values()
    assert sorted(o["actual_output"] for o in outputs) == [
        "via set_output q1",
        "via set_output q2",
    ]


def test_explicit_log_beats_captured_set_output(server: FakeServer) -> None:
    with aiobs.start_experiment("v2", dataset=ROWS, metrics=["hit_at_k"]) as exp:
        item = exp.items()[0]
        with exp.run(item) as run:
            run.log("explicit")
            aiobs.set_output("nested span output")
    (stored,) = server.outputs[exp.id].values()
    assert stored["actual_output"] == "explicit"


def test_context_manager_skips_scoring_on_exception(server: FakeServer) -> None:
    with pytest.raises(ValueError):
        with aiobs.start_experiment("v2", dataset=ROWS) as exp:
            raise ValueError("stop")
    assert exp.result is None
    assert not [c for c in server.calls if c[1].endswith("/evaluate-pack")]


def test_dataframe_input(server: FakeServer) -> None:
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame({"input": ["q1", "q2"], "expected_output": ["a1", None]})
    result = aiobs.evaluate(dataset=df, task=_task, metrics=["hit_at_k"])
    (ds_id,) = server.items
    assert [i["input"] for i in server.items[ds_id]] == ["q1", "q2"]
    assert "expected_output" not in server.items[ds_id][1]
    assert len(result.items) == 2


def test_row_without_input_is_rejected(server: FakeServer) -> None:
    with pytest.raises(ValueError, match="'input'"):
        aiobs.evaluate(dataset=[{"question": "q"}], task=_task)


def test_traced_run_waits_for_binding_then_explicit_output_wins(
    server: FakeServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from aiobs import _otel

    _otel._reset_for_tests()
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    monkeypatch.setattr(_otel, "_INITIALIZED", True)

    # Simulate OTLP ingestion: bound root spans become stored outputs on read.
    original = server.handler

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "GET" and request.url.path.endswith("/outputs"):
            for span in exporter.get_finished_spans():
                attrs = span.attributes or {}
                exp_id = attrs.get("aiobs.experiment_id")
                if exp_id is None:
                    continue
                item_id = str(attrs["aiobs.dataset_item_id"])
                server.outputs[str(exp_id)][item_id] = {
                    "dataset_item_id": item_id,
                    "actual_output": "trace string",
                    "context": {"total_tokens": 7, "documents": [{"id": "trace-doc"}]},
                    "metadata": {"source_trace_id": format(span.context.trace_id, "032x")},
                }
        return original(request)

    monkeypatch.setattr(server, "handler", handler)
    _context._reset_client()
    monkeypatch.setattr(
        _context, "_CLIENT", Client("http://test", transport=httpx2.MockTransport(handler))
    )
    try:
        result = aiobs.evaluate(dataset=ROWS, task=_task, metrics=["hit_at_k"])
    finally:
        _otel._reset_for_tests()

    spans = [s for s in exporter.get_finished_spans() if s.name.startswith("aiobs.eval")]
    assert len(spans) == 2
    assert all(r.trace_id for r in result.items)
    for stored in server.outputs[result.id].values():
        assert stored["actual_output"].startswith("answer to")
        assert stored["context"]["total_tokens"] == 7
        assert stored["context"]["documents"] == [{"id": "trace-doc"}]
        assert stored["metadata"]["source_trace_id"]


def test_app_config_and_run_task(server: FakeServer) -> None:
    exp = aiobs.start_experiment("ab", dataset=ROWS, app_config_id="cfg-1")
    assert server.experiments[exp.id]["app_config_id"] == "cfg-1"
    assert exp.params == {}

    exp.run_task(lambda item: item.input.upper(), max_concurrency=2)
    result = exp.finish()
    assert sorted(o["actual_output"] for o in server.outputs[result.id].values()) == ["Q1", "Q2"]


def test_output_entry_fills_empty_trace_documents() -> None:
    from aiobs.experiment import ItemRun
    from aiobs.models import DatasetItemResponse, ExperimentItemOutputResponse

    run = ItemRun(item=DatasetItemResponse(id="i1"))
    run.log("out", documents=[{"id": "client"}])
    stored = ExperimentItemOutputResponse(dataset_item_id="i1", context={"documents": []})
    assert _output_entry(run, stored)["context"]["documents"] == [{"id": "client"}]


def test_output_entry_keeps_trace_context_and_metadata() -> None:
    from aiobs.experiment import ItemRun
    from aiobs.models import DatasetItemResponse, ExperimentItemOutputResponse

    run = ItemRun(item=DatasetItemResponse(id="i1"))
    run.log("out", documents=[{"id": "client"}], context={"extra": 1})
    run.latency_ms = 12.0
    stored = ExperimentItemOutputResponse(
        dataset_item_id="i1",
        context={"documents": [{"id": "trace"}], "total_tokens": 42},
        metadata={"source_trace_id": "t1"},
    )
    entry = _output_entry(run, stored)
    assert entry["context"] == {
        "documents": [{"id": "trace"}],
        "total_tokens": 42,
        "latency_ms": 12.0,
        "extra": 1,
    }
    assert entry["metadata"] == {"source_trace_id": "t1"}


def test_sample_metric_gets_documents_and_reports_explanation(server: FakeServer) -> None:
    @aiobs.metric(threshold=0.5, version=3, requires=("documents",))
    def cites(sample: aiobs.Sample) -> aiobs.Score:
        hit = any(d["id"] == "d1" for d in sample.documents)
        return aiobs.Score(
            1.0 if hit else 0.0,
            explanation=f"expected={sample.expected}",
            metadata={"n_docs": len(sample.documents)},
        )

    result = aiobs.evaluate(dataset=ROWS, task=_task, metrics=[cites])

    (submitted,) = server.client_results[result.id]
    assert submitted["name"] == "cites"
    assert submitted["threshold"] == 0.5
    assert submitted["config"] == {"version": 3}
    assert sorted(r["explanation"] for r in submitted["results"]) == [
        "expected=a1",
        "expected=a2",
    ]
    assert all(r["score"] == 1.0 for r in submitted["results"])
    assert all(r["metadata"] == {"n_docs": 1} for r in submitted["results"])


def test_missing_required_field_is_submitted_as_skipped(server: FakeServer) -> None:
    @aiobs.metric(requires=("documents",))
    def needs_docs(sample: aiobs.Sample) -> float:
        return 1.0

    result = aiobs.evaluate(dataset=ROWS, task=lambda item: "no retrieval", metrics=[needs_docs])

    (submitted,) = server.client_results[result.id]
    assert [(r["score"], r["label"], r["explanation"]) for r in submitted["results"]] == [
        (None, "SKIPPED", "missing documents"),
        (None, "SKIPPED", "missing documents"),
    ]


def test_async_metric_and_non_finite_score(server: FakeServer) -> None:
    @aiobs.metric
    async def slow(sample: aiobs.Sample) -> float:
        await asyncio.sleep(0)
        return 0.25

    def nan(item: Any, output: Any) -> float:
        return float("nan")

    result = aiobs.evaluate(dataset=ROWS, task=_task, metrics=[slow, nan], max_concurrency=2)

    slow_sub, nan_sub = server.client_results[result.id]
    assert [r["score"] for r in slow_sub["results"]] == [0.25, 0.25]
    assert {r["label"] for r in nan_sub["results"]} == {"ERROR"}
    assert all("finite" in r["explanation"] for r in nan_sub["results"])


def test_non_json_metadata_becomes_item_error(server: FakeServer) -> None:
    def bad_meta(item: Any, output: Any) -> aiobs.Score:
        return aiobs.Score(1.0, metadata={"x": float("nan")})

    result = aiobs.evaluate(dataset=ROWS, task=_task, metrics=[bad_meta])

    (submitted,) = server.client_results[result.id]
    assert {r["label"] for r in submitted["results"]} == {"ERROR"}
    assert all("ValueError" in r["explanation"] for r in submitted["results"])

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import Iterator
from typing import Any

import httpx2
import pytest

import opengrade
from opengrade import Client, _context
from opengrade.experiment import (
    _auto_metrics,
    _chunk_by_bytes,
    _inline_dataset_id,
    _jsonable,
    _output_entry,
)
from opengrade.models import DatasetItemResponse

PROJECT_ID = str(uuid.uuid4())


class FakeServer:
    """Just enough of the platform API for the experiment loop."""

    def __init__(self) -> None:
        self.projects: list[dict[str, Any]] = []
        self.datasets: dict[str, dict[str, Any]] = {}
        self.items: dict[str, list[dict[str, Any]]] = {}
        self.experiments: dict[str, dict[str, Any]] = {}
        self.outputs: dict[str, dict[str, dict[str, Any]]] = {}
        self.metrics_sets: dict[str, dict[str, Any]] = {}
        self.client_results: dict[str, list[dict[str, Any]]] = {}
        self.scored_on_server: set[str] = set()
        self.reject_client_results = False
        self.experiment_metrics: dict[str, dict[str, float]] = {}
        self.aliases: dict[str, str] = {}
        self.fail_metrics = False
        self.summary_repeats = 1
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

        if path.rstrip("/") == "/api/v1/projects":
            if method == "GET":
                return httpx2.Response(200, json=self.projects)
            created = {
                "id": str(uuid.uuid4()),
                "name": body["name"],
                "slug": body["slug"],
                "created_at": "2026-01-01T00:00:00+00:00",
            }
            self.projects.append(created)
            return httpx2.Response(201, json=created)
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
        if m := re.fullmatch(r"/api/v1/projects/[^/]+/experiment-aliases/([^/]+)", path):
            if m[1] not in self.aliases:
                return httpx2.Response(404, json={"detail": "Experiment alias not found"})
            target = self.experiments[self.aliases[m[1]]]
            return httpx2.Response(
                200,
                json={"name": m[1], "experiment_id": target["id"], "experiment": target},
            )
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
                    key = entry["dataset_item_id"]
                    if entry.get("repeat"):
                        key = f"{key}#{entry['repeat']}"
                    current = store.setdefault(
                        key,
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
        if m := re.fullmatch(r"/api/v1/experiments/([^/]+)/metrics", path):
            if m[1] not in self.experiments:
                return httpx2.Response(404, json={"detail": "experiment not found"})
            if self.fail_metrics and method == "PUT":
                return httpx2.Response(500, json={"detail": "boom"})
            store = self.experiment_metrics.setdefault(m[1], {})
            if method == "PUT":
                store.update(body["metrics"])
            return httpx2.Response(200, json={"experiment_id": m[1], "metrics": store})
        if m := re.fullmatch(r"/api/v1/experiments/([^/]+)/params", path):
            if m[1] not in self.experiments:
                return httpx2.Response(404, json={"detail": "experiment not found"})
            if m[1] in self.scored_on_server or m[1] in self.client_results:
                return httpx2.Response(409, json={"detail": "params are locked"})
            exp = self.experiments[m[1]]
            exp["model_config"] = {**exp.get("model_config", {}), **body["params"]}
            return httpx2.Response(200, json=exp)
        if m := re.fullmatch(r"/api/v1/experiments/([^/]+)/runs", path):
            return httpx2.Response(200, json=[])
        if m := re.fullmatch(r"/api/v1/experiments/([^/]+)/summary", path):
            rows = []
            if m[1] in self.scored_on_server:
                rows.append(
                    {
                        "evaluator_name": "hit_at_k",
                        "mean_score": 0.5,
                        "pass_rate": 0.5,
                        "n_repeats": self.summary_repeats,
                        "n_flaky": 1 if self.summary_repeats > 1 else 0,
                    }
                )
            for metric in self.client_results.get(m[1], []):
                scores = [r["score"] for r in metric["results"] if r.get("score") is not None]
                mean = sum(scores) / len(scores) if scores else None
                rows.append({"evaluator_name": metric["name"], "mean_score": mean})
            group_by = request.url.params.get("group_by")
            return httpx2.Response(
                200,
                json={
                    "experiment_id": m[1],
                    "evaluators": rows,
                    "experiment_metrics": self.experiment_metrics.get(m[1], {}),
                    "group_by": group_by,
                    "groups": [{"value": "billing", "n_items": 2, "evaluators": rows}]
                    if group_by
                    else [],
                },
            )
        if m := re.fullmatch(r"/api/v1/experiments/([^/]+)/compare/([^/]+)", path):
            cand = self.experiment_metrics.get(m[1], {})
            base = self.experiment_metrics.get(m[2], {})
            return httpx2.Response(
                200,
                json={
                    "metrics": [
                        {"evaluator_name": "hit_at_k", "delta": -0.25, "status": "regressed"},
                    ],
                    "experiment_metrics": [
                        {
                            "key": k,
                            "candidate": cand.get(k),
                            "baseline": base.get(k),
                            "delta": cand[k] - base[k] if k in cand and k in base else None,
                        }
                        for k in sorted(set(cand) | set(base))
                    ],
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
    monkeypatch.setenv("OPENGRADE_PROJECT_ID", PROJECT_ID)
    monkeypatch.delenv("OPENGRADE_UI_URL", raising=False)
    yield fake
    _context._reset_for_tests()


ROWS = [
    {"input": "q1", "expected_output": "a1", "expected_doc_ids": ["d1"]},
    {"input": "q2", "expected_output": "a2", "expected_doc_ids": ["d2"]},
]


def _task(item: Any) -> str:
    opengrade.set_retrieval_documents([{"id": "d1", "text": "doc"}])
    return f"answer to {item.input}"


def test_evaluate_inline_rows_writes_outputs_and_scores(server: FakeServer) -> None:
    def exact(item: Any, output: Any) -> bool:
        return output == f"answer to {item.input}"

    result = opengrade.evaluate(
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
    assert f"view: {result.url}" in text
    item = result.items[0]
    assert item.url == (
        f"http://test/experiments/{result.id}?item={item.item.id}&project={PROJECT_ID}"
    )


def test_evaluate_prints_the_results_link(
    server: FakeServer, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    result = opengrade.evaluate(dataset=ROWS, task=_task, metrics=["hit_at_k"], name="linked")
    assert f"opengrade: experiment linked -> {result.url}" in capsys.readouterr().err

    monkeypatch.setenv("OPENGRADE_QUIET", "1")
    opengrade.evaluate(dataset=ROWS, task=_task, metrics=["hit_at_k"], name="quiet")
    assert capsys.readouterr().err == ""


def test_evaluate_reuses_inline_dataset_and_metrics_set(server: FakeServer) -> None:
    opengrade.evaluate(dataset=ROWS, task=_task, metrics=["hit_at_k"], name="a")
    opengrade.evaluate(dataset=ROWS, task=_task, metrics=["hit_at_k"], name="b")
    assert len(server.datasets) == 1
    assert len(server.metrics_sets) == 2  # default + one sdk set


def test_evaluate_metrics_set_id_reuses_existing_set(server: FakeServer) -> None:
    first = opengrade.evaluate(dataset=ROWS, task=_task, metrics=["hit_at_k"], name="seed")
    ms_id = server.experiments[first.id]["metrics_set_id"]
    before = len(server.metrics_sets)
    second = opengrade.evaluate(
        dataset=first.experiment.dataset_id,
        task=_task,
        metrics_set_id=ms_id,
        name="clone",
        baseline=first.id,
    )
    assert server.experiments[second.id]["metrics_set_id"] == ms_id
    assert len(server.metrics_sets) == before
    with pytest.raises(ValueError, match="not both"):
        opengrade.evaluate(
            dataset=ROWS, task=_task, metrics=["hit_at_k"], metrics_set_id=ms_id, name="bad"
        )


def test_inline_dataset_resumes_partial_create(server: FakeServer) -> None:
    rows = [{"input": f"q{i}"} for i in range(5)]
    # First call creates the dataset then fails mid-upload.
    calls = {"n": 0}
    original_add = server.handler

    def flaky(request: httpx2.Request) -> httpx2.Response:
        if request.method == "POST" and request.url.path.endswith("/items"):
            calls["n"] += 1
            if calls["n"] == 3:
                return httpx2.Response(503, json={"detail": "blip"})
        return original_add(request)

    server.handler = flaky  # type: ignore[method-assign]
    _context._CLIENT = opengrade.Client("http://test", transport=httpx2.MockTransport(flaky))
    client = opengrade.get_client()
    with pytest.raises(opengrade.OpengradeAPIError):
        _inline_dataset_id(client, PROJECT_ID, rows, task_type="rag_qa")
    assert len(server.datasets) == 1
    ds_id = next(iter(server.datasets))
    assert len(server.items[ds_id]) == 2  # failed on 3rd

    # Second call resumes remaining items.
    _context._CLIENT = opengrade.Client("http://test", transport=httpx2.MockTransport(original_add))
    server.handler = original_add  # type: ignore[method-assign]
    resumed = _inline_dataset_id(opengrade.get_client(), PROJECT_ID, rows, task_type="rag_qa")
    assert resumed == ds_id
    assert len(server.items[ds_id]) == 5


def test_jsonable_replaces_non_finite_floats() -> None:
    assert _jsonable({"x": float("nan"), "y": float("inf"), "z": 1.5}) == {
        "x": None,
        "y": None,
        "z": 1.5,
    }


def test_chunk_by_bytes_splits_large_payloads() -> None:
    items = [{"id": i, "blob": "x" * 1000} for i in range(10)]
    chunks = list(_chunk_by_bytes(items, max_count=100, max_bytes=2500))
    assert len(chunks) > 1
    assert sum(len(c) for c in chunks) == 10
    assert all(len(c) >= 1 for c in chunks)


def test_evaluate_by_dataset_name_with_baseline_by_name(server: FakeServer) -> None:
    ds_id = server.add_dataset("gold-v1", [{"input": "q1"}])
    server.add_experiment("prod", ds_id, "2026-01-01T00:00:00Z")
    newest = server.add_experiment("prod", ds_id, "2026-02-01T00:00:00Z")

    result = opengrade.evaluate(
        dataset="gold-v1", task=lambda item: "x", baseline="prod", max_concurrency=4
    )

    assert server.experiments[result.id]["dataset_id"] == ds_id
    assert server.experiments[result.id]["baseline_experiment_id"] == newest
    assert result.baseline_id == newest
    assert result.comparison is not None
    assert "-0.250 regressed" in result.summary()


def test_baseline_by_alias_uses_promoted_experiment(server: FakeServer) -> None:
    ds_id = server.add_dataset("gold-v1", [{"input": "q1"}])
    promoted = server.add_experiment("ci", ds_id, "2026-01-01T00:00:00Z")
    server.add_experiment("ci", ds_id, "2026-02-01T00:00:00Z")
    server.aliases["main"] = promoted

    result = opengrade.evaluate(dataset="gold-v1", task=lambda item: "x", baseline="alias:main")

    assert result.baseline_id == promoted
    assert server.experiments[result.id]["baseline_experiment_id"] == promoted


def test_baseline_by_missing_alias_is_a_clear_error(server: FakeServer) -> None:
    server.add_dataset("gold-v1", [{"input": "q1"}])
    with pytest.raises(ValueError, match="no experiment alias 'main'"):
        opengrade.evaluate(dataset="gold-v1", task=lambda item: "x", baseline="alias:main")
    with pytest.raises(ValueError, match="empty alias"):
        opengrade.evaluate(dataset="gold-v1", task=lambda item: "x", baseline="alias: ")


def test_metrics_none_uses_project_default_pack(server: FakeServer) -> None:
    opengrade.evaluate(dataset=ROWS, task=_task)
    pack_calls = [c for c in server.calls if c[1].endswith("/evaluate-pack")]
    assert pack_calls and pack_calls[0][2] is None


def test_local_only_metrics_skip_server_scoring(server: FakeServer) -> None:
    result = opengrade.evaluate(dataset=ROWS, task=_task, metrics=[lambda item, out: 0.5])
    assert not [c for c in server.calls if c[1].endswith("/evaluate-pack")]
    assert result.metrics == {"metric_0": 0.5}


def test_local_metric_options_and_failures_are_submitted(server: FakeServer) -> None:
    def flaky_task(item: Any) -> str:
        if item.input == "q2":
            raise RuntimeError("boom")
        return "ok"

    def broken(item: Any, output: Any) -> float:
        raise ValueError("bad metric")

    opengrade.evaluate(
        dataset=ROWS + [{"input": "q3"}],
        task=lambda item: flaky_task(item),
        metrics=[
            opengrade.LocalMetric(
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
    result = opengrade.evaluate(dataset=ROWS, task=_task, metrics=[lambda item, out: 0.5])
    assert result.metrics == {"metric_0": 0.5}
    assert "metric_0 (local only)" in result.summary()


def test_duplicate_local_metric_names_rejected(server: FakeServer) -> None:
    def m(item: Any, out: Any) -> float:
        return 1.0

    with pytest.raises(ValueError, match="duplicate local metric"):
        opengrade.evaluate(dataset=ROWS, task=_task, metrics=[m, opengrade.LocalMetric(m)])


def test_task_errors_are_recorded_not_raised(server: FakeServer) -> None:
    def flaky(item: Any) -> str:
        if item.input == "q2":
            raise RuntimeError("boom")
        return "ok"

    result = opengrade.evaluate(dataset=ROWS, task=flaky, metrics=["hit_at_k"])
    assert [r.error for r in result.errors] == ["RuntimeError: boom"]
    errored = next(o for o in server.outputs[result.id].values() if "error" in o["metadata"])
    assert "actual_output" not in errored

    with pytest.raises(RuntimeError, match="boom"):
        opengrade.evaluate(dataset=ROWS, task=flaky, metrics=["hit_at_k"], raise_on_error=True)


def test_start_experiment_context_manager(server: FakeServer) -> None:
    with opengrade.start_experiment("v2", dataset=ROWS, metrics=["hit_at_k"]) as exp:
        for item in exp.items():
            with exp.run(item):
                opengrade.set_output(f"via set_output {item.input}")

    assert exp.result is not None
    outputs = server.outputs[exp.id].values()
    assert sorted(o["actual_output"] for o in outputs) == [
        "via set_output q1",
        "via set_output q2",
    ]


def test_explicit_log_beats_captured_set_output(server: FakeServer) -> None:
    with opengrade.start_experiment("v2", dataset=ROWS, metrics=["hit_at_k"]) as exp:
        item = exp.items()[0]
        with exp.run(item) as run:
            run.log("explicit")
            opengrade.set_output("nested span output")
    (stored,) = server.outputs[exp.id].values()
    assert stored["actual_output"] == "explicit"


def test_context_manager_skips_scoring_on_exception(server: FakeServer) -> None:
    with pytest.raises(ValueError):
        with opengrade.start_experiment("v2", dataset=ROWS) as exp:
            raise ValueError("stop")
    assert exp.result is None
    assert not [c for c in server.calls if c[1].endswith("/evaluate-pack")]


def test_dataframe_input(server: FakeServer) -> None:
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame({"input": ["q1", "q2"], "expected_output": ["a1", None]})
    result = opengrade.evaluate(dataset=df, task=_task, metrics=["hit_at_k"])
    (ds_id,) = server.items
    assert [i["input"] for i in server.items[ds_id]] == ["q1", "q2"]
    assert "expected_output" not in server.items[ds_id][1]
    assert len(result.items) == 2


def test_polars_dataframe_input(server: FakeServer) -> None:
    pl = pytest.importorskip("polars")
    df = pl.DataFrame({"input": ["q1", "q2"], "expected_output": ["a1", None]})
    result = opengrade.evaluate(dataset=df, task=_task, metrics=["hit_at_k"])
    (ds_id,) = server.items
    assert [i["input"] for i in server.items[ds_id]] == ["q1", "q2"]
    assert len(result.items) == 2


def test_question_alias_accepted(server: FakeServer) -> None:
    result = opengrade.evaluate(
        dataset=[{"question": "q1", "expected_answer": "a1"}],
        task=_task,
        metrics=["hit_at_k"],
    )
    (ds_id,) = server.items
    item = server.items[ds_id][0]
    assert item["input"] == "q1"
    assert item["expected_output"] == "a1"
    assert "question" not in item.get("metadata", {})
    assert len(result.items) == 1


def test_row_without_input_is_rejected(server: FakeServer) -> None:
    with pytest.raises(opengrade.DatasetColumnError, match="missing column") as exc_info:
        opengrade.evaluate(dataset=[{"expected_output": "a"}], task=_task)
    assert exc_info.value.missing == ["input (or question)"]
    assert "expected_output" in exc_info.value.found
    assert "Required: 'input'" in str(exc_info.value)


def test_csv_path_input(server: FakeServer, tmp_path: Any) -> None:
    path = tmp_path / "gold.csv"
    path.write_text("question,expected_answer\nq1,a1\nq2,a2\n", encoding="utf-8")
    result = opengrade.evaluate(dataset=str(path), task=_task, metrics=["hit_at_k"])
    (ds_id,) = server.items
    assert [i["input"] for i in server.items[ds_id]] == ["q1", "q2"]
    assert [i["expected_output"] for i in server.items[ds_id]] == ["a1", "a2"]
    assert len(result.items) == 2


def test_csv_empty_optional_and_json_metadata(server: FakeServer, tmp_path: Any) -> None:
    path = tmp_path / "gold.csv"
    path.write_text(
        'input,expected_output,metadata,context\nq1,,"{""tag"":""x""}","[""c1""]"\nq2,a2,,\n',
        encoding="utf-8",
    )
    opengrade.evaluate(dataset=str(path), task=_task, metrics=["hit_at_k"])
    (ds_id,) = server.items
    items = server.items[ds_id]
    assert "expected_output" not in items[0]
    assert items[0]["metadata"] == {"tag": "x"}
    assert items[0]["context"] == ["c1"]
    assert items[1]["expected_output"] == "a2"
    assert "metadata" not in items[1] or items[1].get("metadata") in (None, {})


def test_csv_invalid_metadata_json_raises(server: FakeServer, tmp_path: Any) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("input,metadata\nq1,not-json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="metadata"):
        opengrade.evaluate(dataset=path, task=_task)


def test_csv_missing_input_column_raises(server: FakeServer, tmp_path: Any) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("expected_answer,expected_doc_ids\na1,pto\n", encoding="utf-8")
    with pytest.raises(opengrade.DatasetColumnError, match=re.escape(str(path))) as exc_info:
        opengrade.evaluate(dataset=path, task=_task)
    assert exc_info.value.missing == ["input (or question)"]
    assert exc_info.value.found == ["expected_answer", "expected_doc_ids"]
    assert "Optional: 'expected_output'" in str(exc_info.value)


def test_jsonl_path_input(server: FakeServer, tmp_path: Any) -> None:
    path = tmp_path / "gold.jsonl"
    path.write_text(
        '{"input": "q1", "expected_output": "a1"}\n{"question": "q2", "expected_answer": "a2"}\n',
        encoding="utf-8",
    )
    result = opengrade.evaluate(dataset=path, task=_task, metrics=["hit_at_k"])
    (ds_id,) = server.items
    assert [i["input"] for i in server.items[ds_id]] == ["q1", "q2"]
    assert len(result.items) == 2


def test_iterable_materialized(server: FakeServer) -> None:
    def rows():
        yield {"input": "q1", "expected_output": "a1"}
        yield {"input": "q2", "expected_output": "a2"}

    result = opengrade.evaluate(dataset=rows(), task=_task, metrics=["hit_at_k"])
    assert len(result.items) == 2
    # Same generator content reused via content-addressed inline dataset.
    same_rows = [
        {"input": "q1", "expected_output": "a1"},
        {"input": "q2", "expected_output": "a2"},
    ]
    opengrade.evaluate(dataset=same_rows, task=_task, metrics=["hit_at_k"])
    assert len(server.datasets) == 1


def test_traced_run_waits_for_binding_then_explicit_output_wins(
    server: FakeServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from opengrade import _otel

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
                exp_id = attrs.get("opengrade.experiment_id")
                if exp_id is None:
                    continue
                item_id = str(attrs["opengrade.dataset_item_id"])
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
        result = opengrade.evaluate(dataset=ROWS, task=_task, metrics=["hit_at_k"])
    finally:
        _otel._reset_for_tests()

    spans = [s for s in exporter.get_finished_spans() if s.name.startswith("opengrade.eval")]
    assert len(spans) == 2
    assert all(r.trace_id for r in result.items)
    for stored in server.outputs[result.id].values():
        assert stored["actual_output"].startswith("answer to")
        assert stored["context"]["total_tokens"] == 7
        assert stored["context"]["documents"] == [{"id": "trace-doc"}]
        assert stored["metadata"]["source_trace_id"]


def test_app_config_and_run_task(server: FakeServer) -> None:
    exp = opengrade.start_experiment("ab", dataset=ROWS, app_config_id="cfg-1")
    assert server.experiments[exp.id]["app_config_id"] == "cfg-1"
    assert exp.params == {}

    exp.run_task(lambda item: item.input.upper(), max_concurrency=2)
    result = exp.finish()
    assert sorted(o["actual_output"] for o in server.outputs[result.id].values()) == ["Q1", "Q2"]


def test_output_entry_fills_empty_trace_documents() -> None:
    from opengrade.experiment import ItemRun
    from opengrade.models import DatasetItemResponse, ExperimentItemOutputResponse

    run = ItemRun(item=DatasetItemResponse(id="i1"))
    run.log("out", documents=[{"id": "client"}])
    stored = ExperimentItemOutputResponse(dataset_item_id="i1", context={"documents": []})
    assert _output_entry(run, stored)["context"]["documents"] == [{"id": "client"}]


def test_output_entry_keeps_trace_context_and_metadata() -> None:
    from opengrade.experiment import ItemRun
    from opengrade.models import DatasetItemResponse, ExperimentItemOutputResponse

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
    @opengrade.metric(threshold=0.5, version=3, requires=("documents",))
    def cites(sample: opengrade.Sample) -> opengrade.Score:
        hit = any(d["id"] == "d1" for d in sample.documents)
        return opengrade.Score(
            1.0 if hit else 0.0,
            explanation=f"expected={sample.expected}",
            metadata={"n_docs": len(sample.documents)},
        )

    result = opengrade.evaluate(dataset=ROWS, task=_task, metrics=[cites])

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
    @opengrade.metric(requires=("documents",))
    def needs_docs(sample: opengrade.Sample) -> float:
        return 1.0

    result = opengrade.evaluate(
        dataset=ROWS, task=lambda item: "no retrieval", metrics=[needs_docs]
    )

    (submitted,) = server.client_results[result.id]
    assert [(r["score"], r["label"], r["explanation"]) for r in submitted["results"]] == [
        (None, "SKIPPED", "missing documents"),
        (None, "SKIPPED", "missing documents"),
    ]


def test_async_metric_and_non_finite_score(server: FakeServer) -> None:
    @opengrade.metric
    async def slow(sample: opengrade.Sample) -> float:
        await asyncio.sleep(0)
        return 0.25

    def nan(item: Any, output: Any) -> float:
        return float("nan")

    result = opengrade.evaluate(dataset=ROWS, task=_task, metrics=[slow, nan], max_concurrency=2)

    slow_sub, nan_sub = server.client_results[result.id]
    assert [r["score"] for r in slow_sub["results"]] == [0.25, 0.25]
    assert {r["label"] for r in nan_sub["results"]} == {"ERROR"}
    assert all("finite" in r["explanation"] for r in nan_sub["results"])


def test_async_task_is_awaited(server: FakeServer) -> None:
    async def async_task(item: Any) -> str:
        await asyncio.sleep(0)
        opengrade.set_retrieval_documents([{"id": "d1", "text": "doc"}])
        return f"answer to {item.input}"

    result = opengrade.evaluate(dataset=ROWS, task=async_task, metrics=["hit_at_k"])
    assert sorted(o["actual_output"] for o in server.outputs[result.id].values()) == [
        "answer to q1",
        "answer to q2",
    ]


def test_evaluate_explicit_client_project_does_not_mutate_global(
    server: FakeServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENGRADE_PROJECT_ID", raising=False)
    explicit = Client("http://test", transport=httpx2.MockTransport(server.handler))
    before = opengrade.get_project()
    opengrade.evaluate(
        dataset=ROWS,
        task=_task,
        metrics=["hit_at_k"],
        project="Demo Project",
        client=explicit,
    )
    assert opengrade.get_project() is before
    assert server.projects[0]["slug"] == "demo-project"
    created_pid = server.projects[0]["id"]
    exp_posts = [
        path
        for method, path, _ in server.calls
        if method == "POST" and path.endswith("/experiments")
    ]
    assert any(created_pid in path for path in exp_posts)


def test_non_json_metadata_becomes_item_error(server: FakeServer) -> None:
    def bad_meta(item: Any, output: Any) -> opengrade.Score:
        return opengrade.Score(1.0, metadata={"x": float("nan")})

    result = opengrade.evaluate(dataset=ROWS, task=_task, metrics=[bad_meta])

    (submitted,) = server.client_results[result.id]
    assert {r["label"] for r in submitted["results"]} == {"ERROR"}
    assert all("ValueError" in r["explanation"] for r in submitted["results"])


def test_client_experiment_metrics_and_params(server: FakeServer) -> None:
    client = opengrade.get_client()
    ds_id = server.add_dataset("gold", [{"input": "q"}])
    exp = client.experiments.create(
        PROJECT_ID, name="e", dataset_id=ds_id, model_config={"model": "a"}
    )

    assert client.experiments.log_metrics(exp.id, {"cost_usd": 1.5}) == {"cost_usd": 1.5}
    assert client.experiments.get_metrics(exp.id) == {"cost_usd": 1.5}
    updated = client.experiments.update_params(exp.id, {"temperature": 0.2})
    assert updated.experiment_model_config == {"model": "a", "temperature": 0.2}


def test_log_params_and_metrics_on_active_experiment(server: FakeServer) -> None:
    with opengrade.start_experiment(
        "v1", dataset=ROWS, metrics=[lambda item, out: 1.0], params={"model": "a"}
    ) as exp:
        assert exp.log_params(temperature=0.2) == {"model": "a", "temperature": 0.2}
        for item in exp.items():
            with exp.run(item) as run:
                run.log("x")
                opengrade.log_metrics({"tokens": 10})  # inside an item run
        opengrade.log_metrics({"cost_usd": 1.5})  # inside the with block

    assert opengrade.experiment.ACTIVE_EXPERIMENT.get() is None
    stored = server.experiment_metrics[exp.id]
    assert stored["cost_usd"] == 1.5
    assert stored["tokens"] == 10
    assert server.experiments[exp.id]["model_config"] == {"model": "a", "temperature": 0.2}


def test_log_params_after_scoring_is_rejected(server: FakeServer) -> None:
    exp = opengrade.start_experiment("v1", dataset=ROWS, metrics=[lambda item, out: 1.0])
    exp.run_task(_task)
    exp.finish()
    with pytest.raises(opengrade.OpengradeAPIError) as err:
        exp.log_params(model="b")
    assert err.value.status == 409


def test_module_level_logging_needs_an_active_experiment() -> None:
    with pytest.raises(RuntimeError, match="no active experiment"):
        opengrade.log_metrics({"x": 1.0})
    with pytest.raises(RuntimeError, match="no active experiment"):
        opengrade.log_params(model="a")


def test_log_methods_reject_empty_input(server: FakeServer) -> None:
    exp = opengrade.start_experiment("v1", dataset=ROWS, metrics=[lambda item, out: 1.0])
    with pytest.raises(ValueError, match="at least one"):
        exp.log_metrics({})
    with pytest.raises(ValueError, match="at least one"):
        exp.log_params()


def test_log_metrics_from_concurrent_workers(server: FakeServer) -> None:
    exp = opengrade.start_experiment("v1", dataset=ROWS, metrics=[lambda item, out: 1.0])

    def task(item: Any) -> str:
        opengrade.log_metrics({f"m_{item.input}": 1.0})
        return "x"

    exp.run_task(task, max_concurrency=4, raise_on_error=True)
    assert {"m_q1", "m_q2"} <= set(server.experiment_metrics[exp.id])


def test_log_metrics_rejects_non_numbers(server: FakeServer) -> None:
    exp = opengrade.start_experiment("v1", dataset=ROWS, metrics=[lambda item, out: 1.0])
    with pytest.raises(ValueError, match="must be a number"):
        exp.log_metrics({"x": True})
    with pytest.raises(ValueError, match="must be a number"):
        exp.log_metrics({"x": "0.9"})  # type: ignore[dict-item]


def test_experiment_reentry_is_rejected(server: FakeServer) -> None:
    exp = opengrade.start_experiment("v1", dataset=ROWS, metrics=[lambda item, out: 1.0])
    with exp:
        with pytest.raises(RuntimeError, match="already active"):
            exp.__enter__()
        exp.run_task(_task)
    assert opengrade.experiment.ACTIVE_EXPERIMENT.get() is None


def test_auto_metrics_percentiles_and_error_rate() -> None:
    from opengrade.experiment import ItemRun

    item = DatasetItemResponse(id="i")
    records = [ItemRun(item=item, latency_ms=v) for v in (10.0, 20.0, 30.0, 40.0)]
    records.append(ItemRun(item=item, latency_ms=5.0, error="RuntimeError: boom"))
    assert _auto_metrics(records) == {
        "opengrade.error_rate": 0.2,
        "opengrade.latency_p50_ms": 20.0,
        "opengrade.latency_p95_ms": 40.0,
    }
    failed = [ItemRun(item=item, latency_ms=1.0, error="x")]
    assert _auto_metrics(failed) == {"opengrade.error_rate": 1.0}


def test_finish_logs_run_metrics_and_exposes_them(server: FakeServer) -> None:
    def flaky(item: Any) -> str:
        if item.input == "q2":
            raise RuntimeError("boom")
        return "ok"

    result = opengrade.evaluate(dataset=ROWS, task=flaky, metrics=[lambda item, out: 1.0])

    stored = server.experiment_metrics[result.id]
    assert stored["opengrade.error_rate"] == 0.5
    assert stored["opengrade.latency_p50_ms"] == stored["opengrade.latency_p95_ms"]
    assert result.experiment_metrics == stored
    assert "opengrade.error_rate" in result.summary()


def test_finish_survives_run_metrics_failure(server: FakeServer) -> None:
    server.fail_metrics = True
    result = opengrade.evaluate(dataset=ROWS, task=_task, metrics=["hit_at_k"])

    assert result.metrics == {"hit_at_k": 0.5}
    assert result.experiment_metrics == {}
    assert not any(
        key.startswith("opengrade.")
        for stored in server.experiment_metrics.values()
        for key in stored
    )


def test_fmt_delta_labels_unchanged_as_not_significant() -> None:
    from opengrade.experiment import _fmt_delta
    from opengrade.models import MetricComparisonResponse

    row = MetricComparisonResponse(delta=-0.083, status="unchanged")
    assert _fmt_delta(row) == "-0.083 not significant"
    row_n = MetricComparisonResponse(delta=0.01, status="insufficient_n")
    assert _fmt_delta(row_n) == "+0.010 insufficient n"
    row_ok = MetricComparisonResponse(delta=0.05, status="improved")
    assert _fmt_delta(row_ok) == "+0.050 improved"


def test_summary_shows_negative_experiment_metric_delta(server: FakeServer) -> None:
    base = opengrade.evaluate(dataset=ROWS, task=_task, metrics=["hit_at_k"], name="base")
    server.experiment_metrics[base.id]["cost_usd"] = 2.5

    with opengrade.start_experiment(
        "cand", dataset=ROWS, metrics=["hit_at_k"], baseline=base
    ) as exp:
        exp.run_task(_task)
        exp.log_metrics({"cost_usd": 2.0})

    assert exp.result is not None
    cost_line = next(line for line in exp.result.summary().splitlines() if "cost_usd" in line)
    assert "-0.500 vs baseline" in cost_line


def test_summary_shows_experiment_metric_delta_vs_baseline(server: FakeServer) -> None:
    base = opengrade.evaluate(dataset=ROWS, task=_task, metrics=["hit_at_k"], name="base")
    server.experiment_metrics[base.id]["cost_usd"] = 1.5

    with opengrade.start_experiment(
        "cand", dataset=ROWS, metrics=["hit_at_k"], baseline=base
    ) as exp:
        exp.run_task(_task)
        exp.log_metrics({"cost_usd": 2.0})

    assert exp.result is not None
    text = exp.result.summary()
    assert "experiment metrics:" in text
    cost_line = next(line for line in text.splitlines() if "cost_usd" in line)
    assert "2.000" in cost_line and "+0.500 vs baseline" in cost_line


def test_start_experiment_records_git_and_default_version(
    server: FakeServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    git = {"commit": "b" * 40, "branch": "main", "dirty": True, "remote_url": None}
    monkeypatch.setattr(opengrade.experiment, "detect_git", lambda: dict(git))

    exp = opengrade.start_experiment("v1", dataset=ROWS, metrics=[lambda item, out: 1.0])
    stored = server.experiments[exp.id]
    assert stored["git"] == git
    assert stored["version"] == "b" * 12 + "-dirty"

    pinned = opengrade.start_experiment(
        "v2", dataset=ROWS, metrics=[lambda item, out: 1.0], version="1.4.0"
    )
    assert server.experiments[pinned.id]["version"] == "1.4.0"

    skipped = opengrade.start_experiment(
        "v3", dataset=ROWS, metrics=[lambda item, out: 1.0], git=False
    )
    assert "git" not in server.experiments[skipped.id]
    assert "version" not in server.experiments[skipped.id]


def test_evaluate_repeats_runs_each_item_n_times(server: FakeServer) -> None:
    server.summary_repeats = 3
    calls: list[str] = []

    def task(item: Any) -> str:
        calls.append(item.input)
        return f"answer {len(calls)}"

    def even(item: Any, output: Any) -> float:
        return float(int(output.split()[-1]) % 2 == 0)

    result = opengrade.evaluate(
        dataset=ROWS, task=task, metrics=["hit_at_k", even], name="rep", repeats=3
    )

    assert sorted(calls) == ["q1"] * 3 + ["q2"] * 3
    assert result.repeats == 3
    assert len(result.items) == 6
    outputs = server.outputs[result.id]
    assert len(outputs) == 6
    repeats = sorted(o.get("repeat", 0) for o in outputs.values())
    assert repeats == [0, 0, 1, 1, 2, 2]

    (submitted,) = server.client_results[result.id]
    pairs = sorted((r["dataset_item_id"], r.get("repeat", 0)) for r in submitted["results"])
    assert len(set(pairs)) == 6

    # Answers 1..6 alternate odd/even: each item averages its own repeats.
    assert result.local_metrics["even"] is not None
    assert result.flaky == {"hit_at_k": 1, "even": 0}
    text = result.summary()
    assert "2 items x 3 repeats" in text
    assert "flaky" in text


def test_manual_loop_repeat_keeps_runs_apart(server: FakeServer) -> None:
    with opengrade.start_experiment("manual-rep", dataset=ROWS, metrics=["hit_at_k"]) as exp:
        (item, _) = exp.items()
        for repeat in range(2):
            with exp.run(item, repeat=repeat) as run:
                run.log(f"out {repeat}")
    assert exp.result is not None
    assert sorted(r.repeat for r in exp.result.items) == [0, 1]
    with pytest.raises(ValueError, match="repeat must be"):
        with exp.run(item, repeat=-1):
            pass


def test_repeats_out_of_range_rejected(server: FakeServer) -> None:
    with pytest.raises(ValueError, match="repeats must be"):
        opengrade.evaluate(dataset=ROWS, task=_task, metrics=["hit_at_k"], repeats=0)


def test_evaluate_group_by_reports_groups(server: FakeServer) -> None:
    result = opengrade.evaluate(
        dataset=ROWS, task=_task, metrics=["hit_at_k"], name="grouped", group_by="category"
    )
    summary_calls = [c for c in server.calls if c[1].endswith("/summary")]
    assert summary_calls
    assert result.groups == {"billing": {"hit_at_k": 0.5}}
    text = result.summary()
    assert "by category:" in text
    assert "billing (n=2)" in text

# ruff: noqa: F811  (the `server` fixture is imported from test_experiment)
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import opengrade
from opengrade import sweeps
from opengrade.retrieval import coerce_document, retrieval_metrics
from opengrade.sweeps import expand_grid, is_lower_better, variant_label
from test_experiment import PROJECT_ID, ROWS, FakeServer, server  # noqa: F401

# --- grid helpers ------------------------------------------------------------------


def test_expand_grid_is_the_cartesian_product_in_key_order() -> None:
    assert expand_grid({"model": ["a", "b"], "k": [3]}) == [
        {"model": "a", "k": 3},
        {"model": "b", "k": 3},
    ]


@pytest.mark.parametrize("grid", [{"k": []}, {"k": "abc"}, {"k": 3}])
def test_expand_grid_rejects_bad_values(grid: dict[str, Any]) -> None:
    with pytest.raises((ValueError, TypeError)):
        expand_grid(grid)


def test_variant_label_and_direction() -> None:
    assert variant_label({"model": "gemma", "k": 5}) == "model=gemma, k=5"
    assert is_lower_better("opengrade.latency_p95_ms")
    assert is_lower_better("opengrade.error_rate")
    assert is_lower_better("cost_usd")
    assert not is_lower_better("hit_at_k")
    assert not is_lower_better("groundedness")


# --- sweep -----------------------------------------------------------------------


def _quality(item: Any, output: Any) -> float:
    return float(output)


def test_sweep_runs_every_configuration_and_ranks_them(server: FakeServer) -> None:
    seen: list[dict[str, Any]] = []

    def task(item: Any, params: dict[str, Any]) -> float:
        seen.append(dict(params))
        opengrade.current().log_metrics({"cost_usd": 2.0 if params["model"] == "big" else 0.5})
        return params["temperature"] / 10 + (0.5 if params["model"] == "big" else 0.0)

    result = opengrade.current().sweep(
        dataset=ROWS,
        task=task,
        grid={"model": ["small", "big"], "temperature": [0, 2]},
        metrics=[_quality],
        name="models",
        params={"prompt": "v3"},
    )

    assert len(result.runs) == 4 and not result.errors
    assert len(server.datasets) == 1  # inline rows uploaded once for every configuration
    assert {(p["model"], p["temperature"]) for p in seen} == {
        ("small", 0),
        ("small", 2),
        ("big", 0),
        ("big", 2),
    }
    exps = [server.experiments[r.id] for r in result.results]
    assert {e["name"] for e in exps} == {
        "models [model=small, temperature=0]",
        "models [model=small, temperature=2]",
        "models [model=big, temperature=0]",
        "models [model=big, temperature=2]",
    }
    for exp in exps:
        assert exp["model_config"]["sweep"] == "models"
        assert exp["model_config"]["prompt"] == "v3"

    best = result.best("_quality")
    assert best is not None and best.params == {"model": "big", "temperature": 2}
    ranked = [run.params for run in result.leaderboard("_quality")]
    assert ranked[-1] == {"model": "small", "temperature": 0}
    # latency: lower is better, so the order flips
    assert result.leaderboard("_quality", lower_is_better=True)[0].params == ranked[-1]

    text = result.summary()
    assert "ranked by _quality (higher is better)" in text
    assert text.index("model=big, temperature=2") < text.index("model=small, temperature=0")
    ids = ",".join(r.id for r in result.results)
    assert result.url == f"http://test/experiments/compare?ids={ids.replace(',', '%2C')}" + (
        f"&project={PROJECT_ID}"
    )
    records = result.to_records()
    assert records[0]["model"] == "small" and "_quality" in records[0]
    assert "opengrade.latency_p95_ms" in records[0]
    assert records[0]["cost_usd"] == 0.5
    assert "cost_usd" in text
    assert result.leaderboard("cost_usd")[0].params["model"] == "small"


def test_sweep_explicit_variants_and_failure_isolation(
    server: FakeServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    def task(item: Any, params: dict[str, Any]) -> float:
        return 1.0

    calls = {"n": 0}
    real_evaluate = sweeps.evaluate

    def flaky_evaluate(**kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("judge down")
        return real_evaluate(**kwargs)

    monkeypatch.setattr(sweeps, "evaluate", flaky_evaluate)
    result = opengrade.current().sweep(
        dataset=ROWS,
        task=task,
        variants=[{"model": "a"}, {"model": "b"}],
        metrics=[_quality],
        name="s",
    )

    assert [run.error for run in result.runs] == ["RuntimeError: judge down", None]
    assert result.best("_quality") is result.runs[1]
    assert "failed: model=a: RuntimeError: judge down" in result.summary()


def test_sweep_argument_validation(server: FakeServer) -> None:
    def one_arg(item: Any) -> str:
        return "x"

    def two_args(item: Any, params: dict[str, Any]) -> str:
        return "x"

    with pytest.raises(ValueError, match="exactly one of grid= or variants="):
        opengrade.current().sweep(dataset=ROWS, task=two_args)
    with pytest.raises(ValueError, match="exactly one of task= or retriever="):
        opengrade.current().sweep(dataset=ROWS, grid={"a": [1]})
    with pytest.raises(TypeError, match=r"accept \(item, params\)"):
        opengrade.current().sweep(dataset=ROWS, task=one_arg, grid={"a": [1]})
    with pytest.raises(ValueError, match="reserved"):
        opengrade.current().sweep(dataset=ROWS, task=two_args, variants=[{"sweep": 1}])
    assert server.experiments == {}


# --- retrieval-only ----------------------------------------------------------------


def test_coerce_document_shapes() -> None:
    assert coerce_document({"id": 7, "text": "t"}) == {"id": "7", "text": "t"}
    plain = coerce_document("some text")
    assert plain["text"] == "some text" and plain["id"].startswith("sha1:")
    lc = SimpleNamespace(page_content="body", metadata={"source": "kb-1"}, id=None)
    assert coerce_document(lc) == {"id": "kb-1", "text": "body", "metadata": {"source": "kb-1"}}
    node = SimpleNamespace(node_id="n-1", get_content=lambda: "node text")
    assert coerce_document(SimpleNamespace(node=node, score=0.9)) == {
        "id": "n-1",
        "text": "node text",
        "score": 0.9,
    }
    assert coerce_document({"text": "t"}, doc_id=lambda d: "custom")["id"] == "custom"
    with pytest.raises(TypeError):
        coerce_document(42)
    with pytest.raises(ValueError):
        coerce_document({"score": 1})


def test_evaluate_retrieval_records_documents_without_an_answer(server: FakeServer) -> None:
    def search(query: str) -> list[dict[str, Any]]:
        return [{"id": "d1", "text": f"doc for {query}"}, "free text"]

    result = opengrade.current().evaluate_retrieval(
        dataset=ROWS, retriever=search, k=3, name="bm25"
    )

    exp = server.experiments[result.id]
    assert exp["model_config"] == {"eval_mode": "retrieval"}
    ms = server.metrics_sets[exp["metrics_set_id"]]
    assert [(e["kind"], e["config"]) for e in ms["entries"]] == [
        ("hit_at_k", {"k": 3}),
        ("recall_at_k", {"k": 3}),
        ("mrr", {"k": 3}),
    ]
    outputs = list(server.outputs[result.id].values())
    assert len(outputs) == 2
    for out in outputs:
        assert out["actual_output"] is None
        docs = out["context"]["documents"]
        assert docs[0]["id"] == "d1" and docs[0]["text"].startswith("doc for q")
        assert docs[1]["id"].startswith("sha1:")
    assert result.errors == []


def test_evaluate_retrieval_passes_the_item_and_rejects_answer_metrics(
    server: FakeServer,
) -> None:
    got: list[Any] = []

    def retrieve(item: Any) -> list[dict[str, Any]]:
        got.append(item)
        return [{"id": "d2"}]

    opengrade.current().evaluate_retrieval(
        dataset=ROWS, retriever=retrieve, metrics=["context_recall"]
    )
    assert {item.input for item in got} == {"q1", "q2"}

    with pytest.raises(ValueError, match="grades a generated answer"):
        opengrade.current().evaluate_retrieval(
            dataset=ROWS, retriever=retrieve, metrics=["groundedness"]
        )
    with pytest.raises(ValueError):
        retrieval_metrics(0)


def test_evaluate_retrieval_async_retriever(server: FakeServer) -> None:
    async def search(query: str) -> list[str]:
        return ["a", "b"]

    result = opengrade.current().evaluate_retrieval(dataset=ROWS, retriever=search)
    outputs = list(server.outputs[result.id].values())
    assert all(len(o["context"]["documents"]) == 2 for o in outputs)


def test_sweep_over_retrievers(server: FakeServer) -> None:
    def retrieve(item: Any, params: dict[str, Any]) -> list[dict[str, Any]]:
        return [{"id": f"d{i}"} for i in range(params["top_k"])]

    result = opengrade.current().sweep(
        dataset=ROWS, retriever=retrieve, grid={"top_k": [1, 4]}, k=4, name="chunks"
    )
    assert not result.errors
    for run in result.runs:
        assert run.result is not None
        exp = server.experiments[run.result.id]
        assert exp["model_config"] == {
            "top_k": run.params["top_k"],
            "sweep": "chunks",
            "eval_mode": "retrieval",
        }
        outputs = list(server.outputs[run.result.id].values())
        assert all(len(o["context"]["documents"]) == run.params["top_k"] for o in outputs)
    assert result.metric_names == ["hit_at_k"]

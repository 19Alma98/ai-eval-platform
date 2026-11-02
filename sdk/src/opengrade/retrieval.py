"""Retrieval-only evaluation: score a retriever on a test set without generating answers."""

from __future__ import annotations

import hashlib
import inspect
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from opengrade._async import run_sync
from opengrade._eval_run import set_retrieval_documents
from opengrade.client import Client
from opengrade.experiment import (
    DatasetLike,
    ExperimentResult,
    Metric,
    _default_name,
    evaluate,
)
from opengrade.models import DatasetItemResponse, ExperimentResponse

RETRIEVAL_METRIC_KINDS = ("hit_at_k", "recall_at_k", "mrr")
"""Default metrics of ``evaluate_retrieval``: deterministic, no LLM judge needed."""

# Server metrics that grade the generated answer: they would only ever be SKIPPED here.
ANSWER_METRIC_KINDS = frozenset(
    {
        "groundedness",
        "correctness",
        "answer_relevance",
        "must_contain",
        "exact_match",
        "contains",
        "regex",
        "json_schema",
    }
)

EVAL_MODE_PARAM = "eval_mode"
"""Param stored on retrieval-only experiments (``"retrieval"``), so the UI can filter them."""


def retrieval_metrics(k: int = 5) -> list[dict[str, Any]]:
    """The default retrieval metrics (hit@k, recall@k, MRR) with cutoff ``k``."""
    if k < 1:
        raise ValueError("k must be >= 1")
    return [{"kind": kind, "config": {"k": k}} for kind in RETRIEVAL_METRIC_KINDS]


def _text_id(text: str) -> str:
    return "sha1:" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def coerce_document(doc: Any, *, doc_id: Callable[[Any], Any] | None = None) -> dict[str, Any]:
    """Turn what a retriever returns into a ``{"id", "text", ...}`` document dict.

    Accepts dicts, plain strings, LangChain ``Document`` (``page_content`` + ``metadata``)
    and LlamaIndex ``NodeWithScore`` (``node`` + ``score``). ``doc_id(doc)`` overrides the id;
    otherwise it comes from ``id`` / ``metadata["id"|"doc_id"|"source"]`` / the node id, and
    falls back to a hash of the text (which cannot match ``expected_doc_ids``).
    """
    out: dict[str, Any]
    if isinstance(doc, Mapping):
        out = dict(doc)
    elif isinstance(doc, str):
        out = {"text": doc}
    elif hasattr(doc, "page_content"):  # LangChain Document
        metadata = dict(getattr(doc, "metadata", None) or {})
        out = {
            "id": getattr(doc, "id", None)
            or metadata.get("id")
            or metadata.get("doc_id")
            or metadata.get("source"),
            "text": doc.page_content,
            "metadata": metadata or None,
        }
    elif hasattr(doc, "node"):  # LlamaIndex NodeWithScore
        node = doc.node
        text = node.get_content() if hasattr(node, "get_content") else getattr(node, "text", None)
        out = {
            "id": getattr(node, "node_id", None) or getattr(node, "id_", None),
            "text": text,
            "score": getattr(doc, "score", None),
        }
    else:
        raise TypeError(
            "retriever must return dicts, strings, LangChain Documents or LlamaIndex "
            f"NodeWithScore objects; got {type(doc).__name__}"
        )
    if doc_id is not None:
        out["id"] = doc_id(doc)
    out = {key: value for key, value in out.items() if value is not None}
    if not str(out.get("id") or "").strip():
        text = out.get("text")
        if not isinstance(text, str) or not text:
            raise ValueError(f"retrieved document has neither an id nor text: {doc!r}")
        out["id"] = _text_id(text)
    else:
        out["id"] = str(out["id"])
    return out


def _check_metrics(metrics: Sequence[Metric]) -> None:
    for metric in metrics:
        kind = metric if isinstance(metric, str) else None
        if isinstance(metric, Mapping):
            kind = metric.get("kind")
        if isinstance(kind, str) and kind.strip().lower() in ANSWER_METRIC_KINDS:
            raise ValueError(
                f"metric {kind!r} grades a generated answer; evaluate_retrieval produces none. "
                "Use retrieval metrics (hit_at_k, recall_at_k, mrr, context_precision, "
                "context_recall) or opengrade.evaluate for the full pipeline."
            )


def retrieval_task(
    retriever: Callable[..., Any],
    *,
    doc_id: Callable[[Any], Any] | None = None,
) -> Callable[[DatasetItemResponse], None]:
    """Wrap ``retriever(item)`` (or ``retriever(query_text)``) as an experiment task.

    The task records the retrieved documents for the item and produces no answer.
    """
    try:
        params = [
            p
            for p in inspect.signature(retriever).parameters.values()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        ]
        wants_text = bool(params) and params[0].name in {"query", "question", "text", "q"}
    except (TypeError, ValueError):
        wants_text = False

    def task(item: DatasetItemResponse) -> None:
        arg: Any = item.input if wants_text else item
        found = retriever(arg)
        if inspect.isawaitable(found):
            found = run_sync(found)
        if found is None:
            found = []
        if isinstance(found, (str, bytes, Mapping)):
            raise TypeError("retriever must return a list of documents")
        set_retrieval_documents([coerce_document(doc, doc_id=doc_id) for doc in found])
        return None

    task.__name__ = getattr(retriever, "__name__", "retriever")
    return task


def evaluate_retrieval(
    *,
    dataset: DatasetLike,
    retriever: Callable[..., Any],
    k: int = 5,
    metrics: Sequence[Metric] | None = None,
    name: str | None = None,
    params: Mapping[str, Any] | None = None,
    baseline: str | ExperimentResponse | ExperimentResult | None = None,
    max_concurrency: int = 1,
    project: str | None = None,
    version: str | None = None,
    git: bool | Mapping[str, Any] = True,
    doc_id: Callable[[Any], Any] | None = None,
    raise_on_error: bool = False,
    timeout: float = 600.0,
    repeats: int = 1,
    group_by: str | None = None,
    client: Client | None = None,
) -> ExperimentResult:
    """Score only the retrieval step of a RAG pipeline: no answer is generated.

    ``retriever(item)`` gets the dataset item (or the question text when its first
    parameter is named ``query``/``question``/``text``/``q``) and returns the ranked
    documents: dicts with ``id`` and ``text``, strings, LangChain ``Document`` or
    LlamaIndex ``NodeWithScore``. Gold ids come from the item's ``expected_doc_ids``.

    Default metrics are hit@k, recall@k and MRR at cutoff ``k`` (no LLM, cheap enough to
    compare chunk sizes, embedding models or rerankers on every change). Add
    ``"context_precision"`` / ``"context_recall"`` to judge relevance and coverage with the
    LLM judge (needs document text and ``expected_output``). Metrics that grade an answer
    are rejected. The experiment is stored with ``params["eval_mode"] = "retrieval"`` and
    the retrieval latency as ``opengrade.latency_p50_ms`` / ``_p95_ms``.
    """
    chosen = list(metrics) if metrics is not None else retrieval_metrics(k)
    _check_metrics(chosen)
    task = retrieval_task(retriever, doc_id=doc_id)
    return evaluate(
        dataset=dataset,
        task=task,
        metrics=chosen,
        name=name or _default_name(task),
        params={**dict(params or {}), EVAL_MODE_PARAM: "retrieval"},
        baseline=baseline,
        max_concurrency=max_concurrency,
        project=project,
        version=version,
        git=git,
        task_type="rag_qa",
        raise_on_error=raise_on_error,
        timeout=timeout,
        repeats=repeats,
        group_by=group_by,
        client=client,
    )


__all__ = ["coerce_document", "evaluate_retrieval", "retrieval_metrics", "retrieval_task"]

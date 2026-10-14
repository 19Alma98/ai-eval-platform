"""Helpers shared by the third-party metric adapters."""

from __future__ import annotations

import importlib
import json
import re
from collections.abc import Iterable, Mapping
from types import ModuleType
from typing import Any

_DOC_TEXT_KEYS = ("content", "text", "page_content")


def import_or_explain(module: str, extra: str) -> ModuleType:
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise ImportError(f"{module} is not installed: pip install 'aiobs-eval[{extra}]'") from exc


def lib_version(module: ModuleType) -> str:
    return str(getattr(module, "__version__", "unknown"))


def as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str, ensure_ascii=False)


def document_texts(documents: Iterable[Mapping[str, Any]]) -> list[str]:
    texts: list[str] = []
    for doc in documents:
        text = next(
            (doc[k] for k in _DOC_TEXT_KEYS if isinstance(doc.get(k), str) and doc[k]),
            None,
        )
        texts.append(text if text is not None else as_text(dict(doc)))
    return texts


def llm_name(llm: Any) -> str | None:
    """Best-effort judge model name from an LLM wrapper (Ragas, LangChain, DeepEval)."""
    for candidate in (llm, getattr(llm, "langchain_llm", None), getattr(llm, "llm", None)):
        if candidate is None:
            continue
        for attr in ("model_name", "model"):
            value = getattr(candidate, attr, None)
            if isinstance(value, str) and value:
                return value
        getter = getattr(candidate, "get_model_name", None)
        if callable(getter):
            try:
                value = getter()
            except Exception:
                value = None
            if isinstance(value, str) and value:
                return value
    return None


def snake(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")

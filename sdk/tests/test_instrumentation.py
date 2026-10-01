from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest
from opentelemetry.sdk.trace import TracerProvider

from aiobs.instrumentation import TIER1, activate_instrumentors


def test_tier1_keys() -> None:
    assert set(TIER1) == {"openai", "anthropic", "langchain", "llama_index", "bedrock"}


def test_skips_missing_packages(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure targets are not importable
    for mod in ("openai", "anthropic", "langchain", "langchain_core", "llama_index", "boto3"):
        monkeypatch.setitem(sys.modules, mod, None)  # type: ignore[arg-type]
        # Better: remove if present
        sys.modules.pop(mod, None)

    provider = TracerProvider()
    activated = activate_instrumentors(None, provider)
    assert activated == []


def test_activates_when_both_present(monkeypatch: pytest.MonkeyPatch) -> None:
    # Fake target library
    sys.modules["openai"] = types.ModuleType("openai")

    fake_mod = types.ModuleType("openinference.instrumentation.openai")
    instrumentor_instance = MagicMock()
    fake_cls = MagicMock(return_value=instrumentor_instance)
    setattr(fake_mod, "OpenAIInstrumentor", fake_cls)

    # Ensure parent packages exist for import machinery
    oi = types.ModuleType("openinference")
    oi_inst = types.ModuleType("openinference.instrumentation")
    sys.modules["openinference"] = oi
    sys.modules["openinference.instrumentation"] = oi_inst
    sys.modules["openinference.instrumentation.openai"] = fake_mod

    provider = TracerProvider()
    activated = activate_instrumentors(["openai"], provider)
    assert activated == ["openai"]
    instrumentor_instance.instrument.assert_called_once_with(tracer_provider=provider)

    # cleanup
    for key in list(sys.modules):
        if key == "openai" or key.startswith("openinference"):
            sys.modules.pop(key, None)


def test_unknown_key_raises() -> None:
    with pytest.raises(ValueError, match="unknown"):
        activate_instrumentors(["not-a-real-key"], TracerProvider())

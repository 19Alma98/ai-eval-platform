from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest
from opentelemetry.sdk.trace import TracerProvider

from opengrade import instrumentation
from opengrade.instrumentation import TIER1, activate_instrumentors, deactivate_instrumentors


def test_tier1_keys() -> None:
    assert set(TIER1) == {"openai", "anthropic", "langchain", "llama_index", "bedrock"}


def test_skips_missing_packages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(instrumentation, "_module_available", lambda _name: False)

    provider = TracerProvider()
    activated = activate_instrumentors(None, provider)
    assert activated == []


def test_module_available_uses_find_spec_not_import(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def boom(name: str):
        calls.append(name)
        raise AssertionError(f"should not import {name}")

    monkeypatch.setattr(instrumentation.importlib, "import_module", boom)
    assert instrumentation._module_available("openai") in (True, False)
    assert calls == []


def test_activates_when_both_present(monkeypatch: pytest.MonkeyPatch) -> None:
    # Fake target library
    sys.modules["openai"] = types.ModuleType("openai")

    fake_mod = types.ModuleType("openinference.instrumentation.openai")
    instrumentor_instance = MagicMock()
    fake_cls = MagicMock(return_value=instrumentor_instance)
    fake_mod.OpenAIInstrumentor = fake_cls

    # Ensure parent packages exist for import machinery
    oi = types.ModuleType("openinference")
    oi_inst = types.ModuleType("openinference.instrumentation")
    sys.modules["openinference"] = oi
    sys.modules["openinference.instrumentation"] = oi_inst
    sys.modules["openinference.instrumentation.openai"] = fake_mod

    monkeypatch.setattr(instrumentation, "_module_available", lambda _name: True)
    deactivate_instrumentors()
    provider = TracerProvider()
    activated = activate_instrumentors(["openai"], provider)
    assert activated == ["openai"]
    instrumentor_instance.instrument.assert_called_once_with(tracer_provider=provider)
    assert instrumentation._ACTIVE == [instrumentor_instance]

    deactivate_instrumentors()
    instrumentor_instance.uninstrument.assert_called_once_with()
    assert instrumentation._ACTIVE == []

    # cleanup
    for key in list(sys.modules):
        if key == "openai" or key.startswith("openinference"):
            sys.modules.pop(key, None)


def test_failing_instrumentor_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "openai", types.ModuleType("openai"))
    fake_mod = types.ModuleType("openinference.instrumentation.openai")
    fake_mod.OpenAIInstrumentor = MagicMock(side_effect=RuntimeError("broken"))
    monkeypatch.setitem(sys.modules, "openinference", types.ModuleType("openinference"))
    oi_inst = types.ModuleType("openinference.instrumentation")
    monkeypatch.setitem(sys.modules, "openinference.instrumentation", oi_inst)
    monkeypatch.setitem(sys.modules, "openinference.instrumentation.openai", fake_mod)
    monkeypatch.setattr(instrumentation, "_module_available", lambda _name: True)

    assert activate_instrumentors(["openai"], TracerProvider()) == []


def test_unknown_key_raises() -> None:
    with pytest.raises(ValueError, match="unknown"):
        activate_instrumentors(["not-a-real-key"], TracerProvider())

from __future__ import annotations

import importlib.metadata

import opengrade


def test_version_matches_opengrade_ai_distribution() -> None:
    assert opengrade.__version__ == importlib.metadata.version("opengrade-ai")
    assert opengrade.__version__ != "0.0.0"

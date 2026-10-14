# backend/tests/test_rename_contract.py
from __future__ import annotations

import importlib.metadata


def test_distribution_name_is_opengrade_ai_server():
    assert importlib.metadata.metadata("opengrade-ai-server")["Name"] == "opengrade-ai-server"


def test_import_package_is_opengrade_server():
    import opengrade_server

    assert opengrade_server.__name__ == "opengrade_server"


def test_console_script_opengrade_server():
    eps = importlib.metadata.entry_points(group="console_scripts")
    matches = [ep for ep in eps if ep.name == "opengrade-server"]
    assert len(matches) == 1
    assert matches[0].value == "opengrade_server.cli:app"

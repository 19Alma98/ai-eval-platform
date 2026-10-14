# sdk/tests/test_rename_contract.py
from __future__ import annotations

import importlib.metadata


def test_distribution_name_is_opengrade_ai():
    assert importlib.metadata.metadata("opengrade-ai")["Name"] == "opengrade-ai"


def test_import_package_is_opengrade():
    import opengrade

    assert opengrade.__name__ == "opengrade"


def test_console_script_opengrade_entry_points():
    eps = importlib.metadata.entry_points(group="console_scripts")
    matches = [ep for ep in eps if ep.name == "opengrade"]
    assert len(matches) == 1
    assert matches[0].value == "opengrade.cli:main"

"""Skip helpers for tests that need the packaged Next.js UI."""

from __future__ import annotations

import pytest

from opengrade_server.ui import ui_root

requires_packaged_ui = pytest.mark.skipif(
    ui_root() is None,
    reason="packaged UI not built (run scripts/package-ui.sh)",
)

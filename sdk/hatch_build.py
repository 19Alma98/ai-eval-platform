"""Build `project.optional-dependencies`, adding the lockstep `ui` extra.

Release builds set OPENGRADE_RELEASE_BUILD=1 so `opengrade-ai[ui]` requires
`opengrade-ai-server==<same version>`.
"""

from __future__ import annotations

import os
from typing import Any

from hatchling.metadata.plugin.interface import MetadataHookInterface

SIBLING = "opengrade-ai-server"


class CustomMetadataHook(MetadataHookInterface):
    def update(self, metadata: dict[str, Any]) -> None:
        pin = f"=={metadata['version']}" if os.environ.get("OPENGRADE_RELEASE_BUILD") == "1" else ""
        extras = {k: list(v) for k, v in self.config.get("optional-dependencies", {}).items()}
        extras["ui"] = [f"{SIBLING}{pin}"]
        metadata["optional-dependencies"] = extras

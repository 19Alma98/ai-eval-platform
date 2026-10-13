"""Build `project.optional-dependencies`, adding the lockstep `ui` extra.

The version comes from the git tag (hatch-vcs). Release builds set
AIOBS_RELEASE_BUILD=1 so `aiobs-eval[ui]` requires `aiobs-eval-server==<same version>`.
Dev builds leave it unpinned (uv resolves the server from ../backend), keeping uv.lock stable.
"""

from __future__ import annotations

import os
from typing import Any

from hatchling.metadata.plugin.interface import MetadataHookInterface

SIBLING = "aiobs-eval-server"


class CustomMetadataHook(MetadataHookInterface):
    def update(self, metadata: dict[str, Any]) -> None:
        pin = f"=={metadata['version']}" if os.environ.get("AIOBS_RELEASE_BUILD") == "1" else ""
        extras = {k: list(v) for k, v in self.config.get("optional-dependencies", {}).items()}
        extras["ui"] = [f"{SIBLING}{pin}"]
        metadata["optional-dependencies"] = extras

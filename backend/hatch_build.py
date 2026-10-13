"""Build `project.dependencies`, adding the lockstep `aiobs-eval` requirement.

The version comes from the git tag (hatch-vcs). Release builds set
AIOBS_RELEASE_BUILD=1 so the published wheel requires `aiobs-eval==<same version>`.
Dev builds leave it unpinned (uv resolves the SDK from ../sdk), keeping uv.lock stable.
"""

from __future__ import annotations

import os
from typing import Any

from hatchling.metadata.plugin.interface import MetadataHookInterface

SIBLING = "aiobs-eval"


class CustomMetadataHook(MetadataHookInterface):
    def update(self, metadata: dict[str, Any]) -> None:
        pin = f"=={metadata['version']}" if os.environ.get("AIOBS_RELEASE_BUILD") == "1" else ""
        metadata["dependencies"] = [*self.config.get("dependencies", []), f"{SIBLING}{pin}"]

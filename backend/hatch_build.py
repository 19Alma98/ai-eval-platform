"""Build `project.dependencies`, adding the lockstep `opengrade-ai` requirement.

Release builds set OPENGRADE_RELEASE_BUILD=1 so the wheel requires
`opengrade-ai==<same version>`.
"""

from __future__ import annotations

import os
from typing import Any

from hatchling.metadata.plugin.interface import MetadataHookInterface

SIBLING = "opengrade-ai"


class CustomMetadataHook(MetadataHookInterface):
    def update(self, metadata: dict[str, Any]) -> None:
        pin = f"=={metadata['version']}" if os.environ.get("OPENGRADE_RELEASE_BUILD") == "1" else ""
        metadata["dependencies"] = [*self.config.get("dependencies", []), f"{SIBLING}{pin}"]

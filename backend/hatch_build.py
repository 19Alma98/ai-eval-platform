"""Build `project.dependencies`, adding the lockstep `opengrade-ai` requirement.

Release builds set OPENGRADE_RELEASE_BUILD=1 so the wheel requires
`opengrade-ai==<same version>`.
"""

from __future__ import annotations

import inspect
import os
from typing import Any

from hatchling.metadata.plugin.interface import MetadataHookInterface
from packaging.version import Version

SIBLING = "opengrade-ai"


def _is_dist_build() -> bool:
    """True when hatchling is building a wheel/sdist (not bare metadata/sync)."""
    for frame in inspect.stack():
        if frame.frame.f_globals.get("__name__", "").startswith("hatchling.builders"):
            return True
    return False


def _require_release_pin(version: str, *, release: bool) -> None:
    if release or not _is_dist_build():
        return
    parsed = Version(version)
    if parsed.is_devrelease or parsed.local is not None:
        return
    raise RuntimeError(
        "Refusing to build a release distribution without OPENGRADE_RELEASE_BUILD=1 "
        f"(version={version!r}). Sibling package pins would be missing. "
        "Set OPENGRADE_RELEASE_BUILD=1 for publish builds, or build from an untagged commit."
    )


class CustomMetadataHook(MetadataHookInterface):
    def update(self, metadata: dict[str, Any]) -> None:
        release = os.environ.get("OPENGRADE_RELEASE_BUILD") == "1"
        _require_release_pin(metadata["version"], release=release)
        pin = f"=={metadata['version']}" if release else ""
        metadata["dependencies"] = [*self.config.get("dependencies", []), f"{SIBLING}{pin}"]

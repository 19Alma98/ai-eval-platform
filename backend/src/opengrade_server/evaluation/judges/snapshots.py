from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aiobs_server.evaluation.judges import prompts

logger = logging.getLogger(__name__)

DEFAULT_SNAPSHOTS_PATH = ".aiobs/judge_prompt_snapshots.json"


def snapshots_path() -> Path:
    raw = os.environ.get("AIOBS_JUDGE_PROMPT_SNAPSHOTS")
    if raw:
        return Path(raw)
    try:
        from aiobs_server.config import get_settings

        return Path(get_settings().judge_prompt_snapshots)
    except Exception:  # noqa: BLE001 — settings may be unavailable in unit tests
        return Path(DEFAULT_SNAPSHOTS_PATH)


def upsert_prompt_snapshot(kind: str, method: str, *, path: Path | None = None) -> None:
    """Best-effort write of the prompt bundle for (kind, method). Never raises."""
    try:
        bundle = prompts.bundle_for(kind, method)
        digest = prompts.content_hash(bundle)
        target = path if path is not None else snapshots_path()
        _write_entry(
            target,
            digest,
            {
                "kind": kind,
                "method": method,
                "prompt_version": prompts.prompt_version(kind, method),
                "bundle": bundle,
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )
    except Exception:  # noqa: BLE001 — audit must not break scoring
        logger.warning(
            "failed to persist judge prompt snapshot for %s.%s", kind, method, exc_info=True
        )


def _write_entry(path: Path, digest: str, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, json.JSONDecodeError):
            data = {}
    data[digest] = entry
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)

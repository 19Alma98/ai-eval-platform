from __future__ import annotations

import os
import re
from pathlib import Path

ENV_FILENAME = ".env"


class DotenvWriteError(Exception):
    """Raised when the ``.env`` file cannot be created or updated."""


def default_env_path() -> Path:
    return Path.cwd() / ENV_FILENAME


def _escape_value(value: str) -> str:
    if re.search(r'[\s#"\']', value) or value == "":
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _line_sets_key(line: str, key: str) -> bool:
    stripped = line.lstrip()
    if not stripped or stripped.startswith("#"):
        return False
    if stripped.startswith("export "):
        stripped = stripped[7:].lstrip()
    return stripped.startswith(f"{key}=") or stripped.startswith(f"{key} =")


def upsert_env_key(key: str, value: str, *, path: Path | None = None) -> Path:
    """Set ``key=value`` in ``path`` (default cwd ``.env``). Creates the file if needed."""
    target = path or default_env_path()
    assignment = f"{key}={_escape_value(value)}\n"
    try:
        if target.is_file():
            text = target.read_text(encoding="utf-8")
            lines = text.splitlines(keepends=True)
            replaced = False
            out: list[str] = []
            for line in lines:
                if _line_sets_key(line, key):
                    if not replaced:
                        out.append(assignment if assignment.endswith("\n") else assignment + "\n")
                        replaced = True
                    continue
                out.append(line if line.endswith("\n") or line == "" else line + "\n")
            if not replaced:
                if out and not out[-1].endswith("\n"):
                    out[-1] = out[-1] + "\n"
                out.append(assignment)
            target.write_text("".join(out), encoding="utf-8")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(assignment, encoding="utf-8")
    except OSError as exc:
        raise DotenvWriteError(
            f"Cannot write {key} to {target}: {exc}. "
            "Set the variable via the process environment or mount a writable .env."
        ) from exc
    return target


def remove_env_key(key: str, *, path: Path | None = None) -> Path | None:
    """Remove assignments of ``key`` from ``path``. No-op if the file is missing."""
    target = path or default_env_path()
    if not target.is_file():
        return None
    try:
        text = target.read_text(encoding="utf-8")
        lines = text.splitlines(keepends=True)
        out = [line for line in lines if not _line_sets_key(line, key)]
        target.write_text("".join(out), encoding="utf-8")
    except OSError as exc:
        raise DotenvWriteError(
            f"Cannot update {target}: {exc}. "
            "Clear the variable via the process environment or a writable .env."
        ) from exc
    return target


def apply_process_env(key: str, value: str | None) -> None:
    """Mirror the file change into ``os.environ`` for the current process."""
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value

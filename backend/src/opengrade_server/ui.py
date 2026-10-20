"""Serve the packaged Next.js static UI from the same process as the API."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Placeholder segment used by frontend generateStaticParams during export.
_PLACEHOLDER = "_"

_DYNAMIC_REWRITES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"^experiments/[^/]+/(compare(?:/.*)?)$"),
        rf"experiments/{_PLACEHOLDER}/\1",
    ),
    (re.compile(r"^experiments/[^/]+(/.*)?$"), rf"experiments/{_PLACEHOLDER}\1"),
    (re.compile(r"^datasets/[^/]+(/.*)?$"), rf"datasets/{_PLACEHOLDER}\1"),
    (re.compile(r"^live-runs/[^/]+(/.*)?$"), rf"live-runs/{_PLACEHOLDER}\1"),
    (re.compile(r"^traces/[^/]+(/.*)?$"), rf"traces/{_PLACEHOLDER}\1"),
    (re.compile(r"^metrics/[^/]+(/.*)?$"), rf"metrics/{_PLACEHOLDER}\1"),
    (re.compile(r"^app-configs/[^/]+(/.*)?$"), rf"app-configs/{_PLACEHOLDER}\1"),
]


def ui_root() -> Path | None:
    """Return the packaged UI directory if present and non-empty."""
    root = Path(__file__).resolve().parent / "_ui"
    if root.is_dir() and (root / "index.html").is_file():
        return root
    return None


def _placeholder_path(cleaned: str) -> str | None:
    for pattern, repl in _DYNAMIC_REWRITES:
        if pattern.match(cleaned):
            return pattern.sub(repl, cleaned)
    return None


def _nested_segment_path(item: str) -> str | None:
    """Older Next exports nest segment prefetch files instead of flattening them.

    The browser asks for ``<page>/__next.!KGFwcCk.<page>.__PAGE__.txt``; those
    builds wrote ``<page>/__next.!KGFwcCk/<page>/__PAGE__.txt``.
    """
    head, _, name = item.rpartition("/")
    if not (name.startswith("__next.") and name.endswith(".txt")):
        return None
    segments = name[len("__next.") : -len(".txt")].split(".")
    if len(segments) < 2:
        return None
    nested = "__next." + "/".join(segments) + ".txt"
    return f"{head}/{nested}" if head else nested


def resolve_ui_file(root: Path, path: str) -> Path | None:
    """Map a request path to a file under the static export."""
    cleaned = path.strip("/")
    if cleaned.startswith("api/") or cleaned.startswith("v1/") or cleaned == "health":
        return None

    paths: list[str] = [cleaned] if cleaned else [""]
    rewritten = _placeholder_path(cleaned) if cleaned else None
    if rewritten and rewritten != cleaned:
        paths.append(rewritten)
    paths += [nested for item in list(paths) if (nested := _nested_segment_path(item))]

    candidates: list[Path] = []
    for item in paths:
        if not item:
            candidates.append(root / "index.html")
            continue
        candidates.append(root / item)
        candidates.append(root / item / "index.html")
        if not item.endswith(".html"):
            candidates.append(root / f"{item}.html")

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            resolved.relative_to(root.resolve())
        except ValueError:
            continue
        if resolved.is_file():
            return resolved
    not_found = root / "404.html"
    if not_found.is_file():
        return not_found
    return None


def mount_ui(app: FastAPI) -> bool:
    """Mount static assets and SPA fallback. Returns True if UI was mounted."""
    root = ui_root()
    if root is None:
        return False

    next_dir = root / "_next"
    if next_dir.is_dir():
        app.mount("/_next", StaticFiles(directory=str(next_dir)), name="next-assets")

    @app.get("/", include_in_schema=False)
    async def ui_index() -> FileResponse:
        return FileResponse(root / "index.html")

    @app.middleware("http")
    async def ui_spa_fallback(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        if response.status_code != 404 or request.method not in ("GET", "HEAD"):
            return response
        path = request.url.path.lstrip("/")
        if path.startswith("api/") or path.startswith("v1/") or path == "health":
            return response
        target = resolve_ui_file(root, path)
        if target is None:
            return response
        status = 404 if target.name == "404.html" else 200
        return FileResponse(target, status_code=status)

    return True

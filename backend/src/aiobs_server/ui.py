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

_DYNAMIC_RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"^experiments/[^/]+/compare/?$"),
        f"experiments/{_PLACEHOLDER}/compare/index.html",
    ),
    (re.compile(r"^experiments/[^/]+/?$"), f"experiments/{_PLACEHOLDER}/index.html"),
    (re.compile(r"^datasets/[^/]+/?$"), f"datasets/{_PLACEHOLDER}/index.html"),
    (re.compile(r"^live-runs/[^/]+/?$"), f"live-runs/{_PLACEHOLDER}/index.html"),
    (re.compile(r"^metrics/[^/]+/?$"), f"metrics/{_PLACEHOLDER}/index.html"),
    (re.compile(r"^app-configs/[^/]+/?$"), f"app-configs/{_PLACEHOLDER}/index.html"),
]


def ui_root() -> Path | None:
    """Return the packaged UI directory if present and non-empty."""
    root = Path(__file__).resolve().parent / "_ui"
    if root.is_dir() and (root / "index.html").is_file():
        return root
    return None


def resolve_ui_file(root: Path, path: str) -> Path | None:
    """Map a request path to a file under the static export."""
    cleaned = path.strip("/")
    if cleaned.startswith("api/") or cleaned.startswith("v1/") or cleaned == "health":
        return None

    candidates: list[Path] = []
    if not cleaned:
        candidates.append(root / "index.html")
    else:
        candidates.append(root / cleaned)
        candidates.append(root / cleaned / "index.html")
        if not cleaned.endswith(".html"):
            candidates.append(root / f"{cleaned}.html")
        for pattern, rel in _DYNAMIC_RULES:
            if pattern.match(cleaned):
                candidates.append(root / rel)
                break

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

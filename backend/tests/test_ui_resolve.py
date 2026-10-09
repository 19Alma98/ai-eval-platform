from pathlib import Path

import pytest
from httpx2 import ASGITransport, AsyncClient

from aiobs_server.main import create_app
from aiobs_server.ui import resolve_ui_file, ui_root


def test_ui_root_detects_packaged_index() -> None:
    root = ui_root()
    assert root is not None
    assert (root / "index.html").is_file()


@pytest.mark.asyncio
async def test_spa_fallback_does_not_405_missing_api_post() -> None:
    """Catch-all GET routes make Starlette 405 non-GET on the same path."""
    app = create_app(mount_packaged_ui=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing_get = await client.get("/api/v1/projects/00000000-0000-0000-0000-000000000001/traces")
        missing_post = await client.post(
            "/api/v1/projects/00000000-0000-0000-0000-000000000001/traces",
            json={},
        )
    assert missing_get.status_code == 404
    assert missing_post.status_code == 404


def test_resolve_dynamic_experiment_path(tmp_path: Path) -> None:
    root = tmp_path / "ui"
    target = root / "experiments" / "_" / "index.html"
    target.parent.mkdir(parents=True)
    target.write_text("<html>exp</html>", encoding="utf-8")
    (root / "index.html").write_text("<html>home</html>", encoding="utf-8")

    resolved = resolve_ui_file(root, "experiments/abc-123")
    assert resolved == target.resolve()


def test_resolve_compare_path(tmp_path: Path) -> None:
    root = tmp_path / "ui"
    target = root / "experiments" / "_" / "compare" / "index.html"
    target.parent.mkdir(parents=True)
    target.write_text("<html>cmp</html>", encoding="utf-8")
    (root / "index.html").write_text("<html>home</html>", encoding="utf-8")

    resolved = resolve_ui_file(root, "experiments/abc-123/compare/")
    assert resolved == target.resolve()

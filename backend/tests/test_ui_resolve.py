from pathlib import Path

import pytest
from httpx2 import ASGITransport, AsyncClient

from opengrade_server.main import create_app
from opengrade_server.ui import resolve_ui_file, ui_root
from support.packaged_ui import requires_packaged_ui


@requires_packaged_ui
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
        missing_get = await client.get(
            "/api/v1/projects/00000000-0000-0000-0000-000000000001/no-such-route"
        )
        missing_post = await client.post(
            "/api/v1/projects/00000000-0000-0000-0000-000000000001/no-such-route",
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


def test_resolve_dynamic_next_tree_files(tmp_path: Path) -> None:
    """Soft-nav RSC files exist only under the export placeholder segment."""
    root = tmp_path / "ui"
    dataset_tree = root / "datasets" / "_" / "__next._tree.txt"
    compare_tree = root / "experiments" / "_" / "compare" / "__next._tree.txt"
    dataset_tree.parent.mkdir(parents=True)
    compare_tree.parent.mkdir(parents=True)
    dataset_tree.write_text("dataset-tree", encoding="utf-8")
    compare_tree.write_text("compare-tree", encoding="utf-8")
    (root / "index.html").write_text("<html>home</html>", encoding="utf-8")

    assert (
        resolve_ui_file(root, "datasets/087686a3-93db-49a9-b3ac-248bbe8fb1e3/__next._tree.txt")
        == dataset_tree.resolve()
    )
    assert (
        resolve_ui_file(
            root,
            "experiments/50af5c63-0741-42cd-9a43-e436efa9391c/compare/__next._tree.txt",
        )
        == compare_tree.resolve()
    )


def test_resolve_dynamic_trace_path(tmp_path: Path) -> None:
    root = tmp_path / "ui"
    target = root / "traces" / "_" / "index.html"
    target.parent.mkdir(parents=True)
    target.write_text("<html>trace</html>", encoding="utf-8")
    (root / "index.html").write_text("<html>home</html>", encoding="utf-8")

    assert resolve_ui_file(root, "traces/" + "ab" * 16) == target.resolve()

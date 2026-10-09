from pathlib import Path

from aiobs_server.ui import resolve_ui_file, ui_root


def test_ui_root_detects_packaged_index() -> None:
    root = ui_root()
    assert root is not None
    assert (root / "index.html").is_file()


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

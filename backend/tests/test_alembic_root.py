"""Unit tests for Alembic root resolution (editable vs Docker layouts)."""

from pathlib import Path

import pytest

import opengrade_server.infrastructure.db as db_module
from opengrade_server.infrastructure.db import (
    _alembic_config,
    _is_alembic_root,
    _resolve_alembic_root,
)


def _write_alembic_tree(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "alembic.ini").write_text("[alembic]\nscript_location = alembic\n", encoding="utf-8")
    (root / "alembic").mkdir()


def test_resolve_alembic_root_editable_monorepo_layout() -> None:
    """Running tests from the backend tree uses the package-relative backend root."""
    backend_root = Path(__file__).resolve().parents[1]
    assert _is_alembic_root(backend_root)
    assert _resolve_alembic_root() == backend_root


def test_resolve_alembic_root_prefers_cwd_when_package_path_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docker_app = tmp_path / "app"
    _write_alembic_tree(docker_app)

    site_packages = tmp_path / "lib" / "python3.12" / "site-packages"
    pkg_dir = site_packages / "opengrade_server" / "infrastructure"
    pkg_dir.mkdir(parents=True)
    fake_db = pkg_dir / "db.py"
    fake_db.write_text("# stub\n", encoding="utf-8")

    monkeypatch.setattr(db_module, "__file__", str(fake_db))
    monkeypatch.chdir(docker_app)

    assert _resolve_alembic_root() == docker_app


def test_resolve_alembic_root_app_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When cwd is not the migration root, ``/app`` is used if present."""
    site_packages = tmp_path / "lib" / "site-packages"
    pkg_dir = site_packages / "opengrade_server" / "infrastructure"
    pkg_dir.mkdir(parents=True)
    fake_db = pkg_dir / "db.py"
    fake_db.write_text("# stub\n", encoding="utf-8")

    monkeypatch.setattr(db_module, "__file__", str(fake_db))
    (tmp_path / "empty").mkdir()
    monkeypatch.chdir(tmp_path / "empty")

    app_root = tmp_path / "app"
    _write_alembic_tree(app_root)

    real_path = Path

    class PathWrapper:
        def __call__(self, *args: object, **kwargs: object) -> Path:
            if args and args[0] == "/app":
                return app_root
            return real_path(*args, **kwargs)

        def __getattr__(self, name: str) -> object:
            return getattr(real_path, name)

    monkeypatch.setattr(db_module, "Path", PathWrapper())

    assert _resolve_alembic_root() == app_root


def test_alembic_config_prepend_sys_path_uses_src_when_present() -> None:
    cfg = _alembic_config()
    backend_root = _resolve_alembic_root()
    src = backend_root / "src"
    if src.is_dir():
        assert cfg.get_main_option("prepend_sys_path") == str(src)
    assert cfg.get_main_option("script_location") == str(backend_root / "alembic")

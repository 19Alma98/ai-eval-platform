"""Migrations ship inside ``opengrade_server`` and resolve without a repo checkout."""

from pathlib import Path

import pytest
from alembic.script import ScriptDirectory

import opengrade_server
from opengrade_server.infrastructure.db import MIGRATIONS_DIR, _alembic_config


def test_migrations_dir_is_inside_the_package() -> None:
    package_dir = Path(opengrade_server.__file__).resolve().parent
    assert MIGRATIONS_DIR == package_dir / "migrations"
    assert (MIGRATIONS_DIR / "env.py").is_file()
    assert (MIGRATIONS_DIR / "script.py.mako").is_file()


def test_alembic_config_does_not_depend_on_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pip install runs from any directory, with no alembic.ini next to it."""
    monkeypatch.chdir(tmp_path)
    cfg = _alembic_config()
    assert cfg.config_file_name is None
    assert cfg.get_main_option("script_location") == str(MIGRATIONS_DIR)

    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1
    assert len(list(script.walk_revisions())) > 1

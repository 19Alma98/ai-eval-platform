from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from opengrade._git import detect_git, version_from_git, web_url

_CI_VARS = (
    "GITHUB_SHA",
    "GITHUB_HEAD_REF",
    "GITHUB_REF_NAME",
    "GITHUB_SERVER_URL",
    "GITHUB_REPOSITORY",
    "CI_COMMIT_SHA",
    "CI_COMMIT_REF_NAME",
    "CI_PROJECT_URL",
    "OPENGRADE_DISABLE_GIT",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _CI_VARS:
        monkeypatch.delenv(name, raising=False)


def _run(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _run(tmp_path, "init", "-q", "-b", "feature/x")
    _run(tmp_path, "config", "user.email", "t@example.com")
    _run(tmp_path, "config", "user.name", "t")
    (tmp_path / "app.py").write_text("print(1)\n")
    _run(tmp_path, "add", "app.py")
    _run(tmp_path, "commit", "-q", "-m", "init")
    _run(
        tmp_path,
        "remote",
        "add",
        "origin",
        "https://x-access-token:secret@github.com/acme/app.git",
    )
    return tmp_path


def test_detects_commit_branch_and_strips_credentials(repo: Path) -> None:
    info = detect_git(str(repo))

    assert info == {
        "commit": _run(repo, "rev-parse", "HEAD"),
        "branch": "feature/x",
        "dirty": False,
        "remote_url": "https://github.com/acme/app",
    }


def test_uncommitted_changes_mark_dirty(repo: Path) -> None:
    (repo / "app.py").write_text("print(2)\n")
    (repo / "untracked.txt").write_text("ignored\n")

    info = detect_git(str(repo))

    assert info is not None and info["dirty"] is True
    assert version_from_git(info) == info["commit"][:12] + "-dirty"


def test_detached_head_takes_branch_from_ci(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _run(repo, "checkout", "-q", "--detach")
    monkeypatch.setenv("GITHUB_HEAD_REF", "fix/retrieval")

    info = detect_git(str(repo))

    assert info is not None and info["branch"] == "fix/retrieval"


def test_ci_env_fallback_without_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/app")

    assert detect_git(str(tmp_path)) == {
        "commit": "a" * 40,
        "branch": "main",
        "remote_url": "https://github.com/acme/app",
    }


def test_no_revision_or_opt_out(
    tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    outside = tmp_path.parent / "not-a-repo"
    outside.mkdir(exist_ok=True)
    assert detect_git(str(outside)) is None

    monkeypatch.setenv("OPENGRADE_DISABLE_GIT", "1")
    assert detect_git(str(repo)) is None


@pytest.mark.parametrize(
    ("remote", "expected"),
    [
        ("git@github.com:acme/app.git", "https://github.com/acme/app"),
        ("ssh://git@gitlab.example.com:2222/grp/app.git", "https://gitlab.example.com/grp/app"),
        ("https://user:tok@gitlab.com/grp/sub/app.git/", "https://gitlab.com/grp/sub/app"),
        ("/srv/git/app.git", None),
        (None, None),
    ],
)
def test_web_url(remote: str | None, expected: str | None) -> None:
    assert web_url(remote) == expected

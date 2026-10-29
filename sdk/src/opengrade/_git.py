"""Detect the code revision an experiment runs at (local git checkout, else CI env)."""

from __future__ import annotations

import os
import re
import subprocess
from typing import Any
from urllib.parse import urlsplit, urlunsplit

_TIMEOUT_S = 2.0
_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
# scp-like ssh remote: git@github.com:owner/repo.git
_SCP_RE = re.compile(r"^(?:[^@/]+@)?(?P<host>[^:/]+):(?P<path>[^/].*)$")

# (commit, branch) env vars per CI, first match wins.
_CI_COMMIT_VARS = (
    "GITHUB_SHA",
    "CI_COMMIT_SHA",  # GitLab
    "BITBUCKET_COMMIT",
    "CIRCLE_SHA1",
    "BUILDKITE_COMMIT",
    "GIT_COMMIT",  # Jenkins
)
_CI_BRANCH_VARS = (
    "GITHUB_HEAD_REF",  # set on pull_request events; GITHUB_REF_NAME is then "N/merge"
    "GITHUB_REF_NAME",
    "CI_COMMIT_REF_NAME",
    "BITBUCKET_BRANCH",
    "CIRCLE_BRANCH",
    "BUILDKITE_BRANCH",
    "GIT_BRANCH",
)


def _env(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return None


def _git(args: list[str], cwd: str | None) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def web_url(remote: str | None) -> str | None:
    """Browsable https URL for a git remote, without credentials or ``.git``."""
    if not remote:
        return None
    remote = remote.strip()
    if "://" not in remote:
        match = _SCP_RE.match(remote)
        if match is None:
            return None
        remote = f"https://{match['host']}/{match['path']}"
    parts = urlsplit(remote)
    if parts.scheme not in ("http", "https", "ssh", "git") or not parts.hostname:
        return None
    host = parts.hostname
    if parts.port and parts.scheme in ("http", "https"):
        host = f"{host}:{parts.port}"
    path = parts.path.rstrip("/").removesuffix(".git")
    return urlunsplit(("https", host, path, "", ""))


def _ci_remote() -> str | None:
    server, repo = os.getenv("GITHUB_SERVER_URL"), os.getenv("GITHUB_REPOSITORY")
    if server and repo:
        return f"{server.rstrip('/')}/{repo}"
    return os.getenv("CI_PROJECT_URL") or None


def detect_git(cwd: str | None = None) -> dict[str, Any] | None:
    """Return ``{commit, branch, dirty, remote_url}`` or None when no revision is known.

    Reads the git checkout around ``cwd``; falls back to CI env vars (e.g. a Docker
    build without ``.git``). Set ``OPENGRADE_DISABLE_GIT=1`` to opt out.
    """
    if os.getenv("OPENGRADE_DISABLE_GIT", "").strip().lower() in ("1", "true", "yes"):
        return None
    info: dict[str, Any] = {}
    commit = _git(["rev-parse", "HEAD"], cwd)
    if commit and _SHA_RE.match(commit):
        info["commit"] = commit
        branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
        # Detached HEAD (CI checkouts) reports "HEAD": the CI env knows the branch.
        info["branch"] = branch if branch and branch != "HEAD" else _env(_CI_BRANCH_VARS)
        status = _git(["status", "--porcelain", "--untracked-files=no"], cwd)
        info["dirty"] = None if status is None else bool(status)
        info["remote_url"] = web_url(_git(["config", "--get", "remote.origin.url"], cwd))
    else:
        commit = _env(_CI_COMMIT_VARS)
        if not commit or not _SHA_RE.match(commit):
            return None
        info["commit"] = commit
        info["branch"] = _env(_CI_BRANCH_VARS)
        info["remote_url"] = web_url(_ci_remote())
    if not info.get("remote_url"):
        info["remote_url"] = web_url(_ci_remote())
    return {k: v for k, v in info.items() if v is not None}


def version_from_git(git: dict[str, Any] | None) -> str | None:
    """Short SHA (``-dirty`` when uncommitted changes) as the default experiment version."""
    if not git or not git.get("commit"):
        return None
    return str(git["commit"])[:12] + ("-dirty" if git.get("dirty") else "")

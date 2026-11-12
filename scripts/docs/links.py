"""MkDocs hook: make repo-relative links work on the docs site.

The Markdown in docs/ (and sdk/README.md, included as the SDK page) is written for
GitHub, so it links to files outside docs/: ``../examples/...``, ``../sdk/README.md``,
``../.github/workflows/...``. MkDocs cannot serve those. This hook rewrites them:

- a link to sdk/README.md becomes the site's SDK page;
- a link to a file in docs/ (also as a GitHub URL) becomes a link to that page;
- any other repository path becomes a GitHub URL.

It also expands ``--8<-- "path/from/repo/root"`` lines with that file's content
(before rewriting, so links in the included file are fixed too). Relative links in the
included file are first rebased from its own directory onto the including page.
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path

REPO_URL = "https://github.com/19Alma98/ai-eval-platform"
BRANCH = "main"
ROOT = Path(__file__).resolve().parents[2]
DOCS = "docs"
# Repository files rendered as a site page: repo path -> docs page.
PAGES = {
    "sdk/README.md": "sdk.md",
    "CHANGELOG.md": "changelog.md",
    "CONTRIBUTING.md": "contributing.md",
}

_INCLUDE = re.compile(r'^--8<-- "(?P<path>[^"]+)"[ \t]*$', re.M)
_LINK = re.compile(r"(?<!!)\]\((?P<url>[^)\s]+)\)")
_FENCE = re.compile(r"^(```|~~~).*?^\1", re.M | re.S)
_GITHUB_DOCS = re.compile(
    re.escape(REPO_URL) + r"/blob/" + re.escape(BRANCH) + r"/(?P<path>[^)#\s]+)(?P<frag>#[^)\s]*)?"
)


def _to_page(repo_path: str, page_src: str) -> str | None:
    """Relative link from ``page_src`` (docs-relative) to the page for ``repo_path``."""
    target = PAGES.get(repo_path)
    if target is None and repo_path.startswith(DOCS + "/") and repo_path.endswith(".md"):
        target = repo_path[len(DOCS) + 1 :]
    if target is None:
        return None
    return posixpath.relpath(target, posixpath.dirname(page_src) or ".")


def _rewrite(url: str, page_src: str) -> str:
    gh = _GITHUB_DOCS.fullmatch(url)
    if gh:
        local = _to_page(gh["path"], page_src)
        return local + (gh["frag"] or "") if local else url
    if re.match(r"^[a-z][a-z0-9+.-]*:|^#|^/", url, re.I):
        return url
    path, _, frag = url.partition("#")
    repo_path = posixpath.normpath(posixpath.join(DOCS, posixpath.dirname(page_src), path))
    local = _to_page(repo_path, page_src)
    if local:
        return local + (f"#{frag}" if frag else "")
    if repo_path.startswith(DOCS + "/") and repo_path not in PAGES:
        return url
    kind = "tree" if (ROOT / repo_path).is_dir() else "blob"
    return f"{REPO_URL}/{kind}/{BRANCH}/{repo_path}" + (f"#{frag}" if frag else "")


def _rebase(text: str, included: str, page_src: str) -> str:
    """Make relative links of ``included`` (repo path) relative to docs page ``page_src``."""
    src_dir = posixpath.dirname(included)
    page_dir = posixpath.join(DOCS, posixpath.dirname(page_src))

    def fix(m: re.Match[str]) -> str:
        url = m["url"]
        if re.match(r"^[a-z][a-z0-9+.-]*:|^#|^/", url, re.I):
            return m.group(0)
        path, sep, frag = url.partition("#")
        target = posixpath.normpath(posixpath.join(src_dir, path))
        return f"]({posixpath.relpath(target, page_dir)}{sep}{frag})"

    return _map_outside_fences(text, lambda chunk: _LINK.sub(fix, chunk))


def _include(m: re.Match[str], page_src: str) -> str:
    path = (ROOT / m["path"]).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        raise FileNotFoundError(f"docs include not found: {m['path']}")
    return _rebase(path.read_text(encoding="utf-8"), m["path"], page_src)


def _map_outside_fences(markdown: str, fn) -> str:  # noqa: ANN001 — str -> str
    out, last = [], 0
    for fence in _FENCE.finditer(markdown):  # leave fenced code blocks alone
        out.append(fn(markdown[last : fence.start()]))
        out.append(fence.group(0))
        last = fence.end()
    out.append(fn(markdown[last:]))
    return "".join(out)


def on_page_markdown(markdown: str, page, **_) -> str:
    src = page.file.src_uri
    for repo_path, docs_page in PAGES.items():
        if src == docs_page:  # "Edit this page" opens the real source
            page.edit_url = f"{REPO_URL}/edit/{BRANCH}/{repo_path}"
    markdown = _INCLUDE.sub(lambda m: _include(m, src), markdown)
    return _map_outside_fences(
        markdown, lambda chunk: _LINK.sub(lambda m: f"]({_rewrite(m['url'], src)})", chunk)
    )

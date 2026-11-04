"""MkDocs hook: make repo-relative links work on the docs site.

The Markdown in docs/ (and sdk/README.md, included as the SDK page) is written for
GitHub, so it links to files outside docs/: ``../examples/...``, ``../sdk/README.md``,
``../.github/workflows/...``. MkDocs cannot serve those. This hook rewrites them:

- a link to sdk/README.md becomes the site's SDK page;
- a link to a file in docs/ (also as a GitHub URL) becomes a link to that page;
- any other repository path becomes a GitHub URL.

It also expands ``--8<-- "path/from/repo/root"`` lines with that file's content
(before rewriting, so links in the included file are fixed too).
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
PAGES = {"sdk/README.md": "sdk.md"}

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
    if repo_path.startswith(DOCS + "/") and repo_path not in PAGES:
        return url  # inside docs/: MkDocs resolves and validates it
    local = _to_page(repo_path, page_src)
    if local:
        return local + (f"#{frag}" if frag else "")
    kind = "tree" if (ROOT / repo_path).is_dir() else "blob"
    return f"{REPO_URL}/{kind}/{BRANCH}/{repo_path}" + (f"#{frag}" if frag else "")


def _include(m: re.Match[str]) -> str:
    path = (ROOT / m["path"]).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        raise FileNotFoundError(f"docs include not found: {m['path']}")
    return path.read_text(encoding="utf-8")


def on_page_markdown(markdown: str, page, **_) -> str:
    src = page.file.src_uri
    for repo_path, docs_page in PAGES.items():
        if src == docs_page:  # "Edit this page" opens the real source
            page.edit_url = f"{REPO_URL}/edit/{BRANCH}/{repo_path}"
    markdown = _INCLUDE.sub(_include, markdown)
    out, last = [], 0
    # Leave fenced code blocks alone.
    for fence in _FENCE.finditer(markdown):
        out.append(_LINK.sub(lambda m: f"]({_rewrite(m['url'], src)})", markdown[last : fence.start()]))
        out.append(fence.group(0))
        last = fence.end()
    out.append(_LINK.sub(lambda m: f"]({_rewrite(m['url'], src)})", markdown[last:]))
    return "".join(out)

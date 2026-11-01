"""mkdocs hook (T0.4): links from the docs to repo files outside ``docs/`` point at GitHub.

``REVIEW.md``, ``tasks/`` and ``prompts/`` reach the site through include-markdown stubs, and a
few docs link to ``../../tasks/...``. Those targets are not site pages, so strict mode would call
every one a broken link. This hook rewrites exactly the relative links that leave ``docs/`` and
**exist** in the repo to ``https://github.com/<repo>/blob/main/<path>``. A link to a file that does
not exist is left alone and still fails ``mkdocs build --strict``.
"""

import posixpath
import re
from pathlib import Path
from typing import Any

REPO_URL = "https://github.com/dheena18/pruefstand"
DOCS_DIR = "docs"
_FENCE = re.compile(r"^\s*(```|~~~)")
_LINK = re.compile(r"(\]\()([^)\s#]+)(#[^)\s]*)?(\))")
_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)


def rewrite_outside_links(markdown: str, src_uri: str, repo_root: Path) -> str:
    """Rewrite relative Markdown links that leave ``docs/`` to GitHub URLs.

    Args:
        markdown: Page source after plugins (include-markdown has already run).
        src_uri: The page path relative to ``docs/`` (``_external/prompts.md``).
        repo_root: Repository root, used to check that a target exists.

    Returns:
        The page with each existing outside target replaced by a ``blob``/``tree`` URL on
        GitHub; code fences and every other link are untouched.
    """
    out: list[str] = []
    in_fence = False
    for line in markdown.split("\n"):
        if _FENCE.match(line):
            in_fence = not in_fence
        out.append(line if in_fence else _LINK.sub(lambda m: _replace(m, src_uri, repo_root), line))
    return "\n".join(out)


def _replace(match: "re.Match[str]", src_uri: str, repo_root: Path) -> str:
    target = match.group(2)
    if _SCHEME.match(target) or target.startswith("/"):
        return match.group(0)
    page_dir = posixpath.dirname(posixpath.join(DOCS_DIR, src_uri))
    repo_path = posixpath.normpath(posixpath.join(page_dir, target))
    if repo_path == DOCS_DIR or repo_path.startswith(f"{DOCS_DIR}/") or repo_path.startswith(".."):
        return match.group(0)
    path = repo_root / repo_path
    if not path.exists():
        return match.group(0)
    kind = "tree" if path.is_dir() else "blob"
    anchor = match.group(3) or ""
    return f"{match.group(1)}{REPO_URL}/{kind}/main/{repo_path}{anchor}{match.group(4)}"


def on_page_markdown(markdown: str, page: Any, config: Any, files: Any) -> str:  # noqa: ANN401
    """Mkdocs entry point: apply :func:`rewrite_outside_links` to every page.

    Args:
        markdown: Page source.
        page: The mkdocs page (``page.file.src_uri`` is used).
        config: The mkdocs config (``config.config_file_path`` locates the repo root).
        files: Unused.

    Returns:
        The rewritten page source.
    """
    del files
    repo_root = Path(str(config["config_file_path"])).resolve().parent
    return rewrite_outside_links(markdown, str(page.file.src_uri), repo_root)

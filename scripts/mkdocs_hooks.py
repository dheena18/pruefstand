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
# A code span opens with a run of N backticks and closes with a run of exactly N.
_CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`).+?(?<!`)\1(?!`)")
_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)


def rewrite_outside_links(
    markdown: str, src_uri: str, repo_root: Path, site_files: frozenset[str] | None = None
) -> str:
    """Rewrite relative Markdown links that leave ``docs/`` to GitHub URLs.

    Args:
        markdown: Page source after plugins (include-markdown has already run).
        src_uri: The page path relative to ``docs/`` (``_external/prompts.md``).
        repo_root: Repository root, used to check that a target exists.
        site_files: Paths (relative to ``docs/``) that are pages of the built site. A link into
            ``docs/`` to an existing file not in this set (an ``exclude_docs`` file) is rewritten
            too; ``None`` leaves every link into ``docs/`` alone.

    Returns:
        The page with each existing outside target replaced by a ``blob``/``tree`` URL on
        GitHub; code fences, inline code spans and every other link are untouched.
    """
    out: list[str] = []
    in_fence = False
    for line in markdown.split("\n"):
        if _FENCE.match(line):
            in_fence = not in_fence
        out.append(line if in_fence else _rewrite_line(line, src_uri, repo_root, site_files))
    return "\n".join(out)


def _rewrite_line(
    line: str, src_uri: str, repo_root: Path, site_files: frozenset[str] | None
) -> str:
    """Rewrite the links of one line, leaving inline code spans alone."""

    def links(text: str) -> str:
        return _LINK.sub(lambda m: _replace(m, src_uri, repo_root, site_files), text)

    out: list[str] = []
    pos = 0
    for span in _CODE_SPAN.finditer(line):
        out += [links(line[pos : span.start()]), span.group(0)]
        pos = span.end()
    out.append(links(line[pos:]))
    return "".join(out)


def _replace(
    match: "re.Match[str]", src_uri: str, repo_root: Path, site_files: frozenset[str] | None
) -> str:
    target = match.group(2)
    if _SCHEME.match(target) or target.startswith("/"):
        return match.group(0)
    page_dir = posixpath.dirname(posixpath.join(DOCS_DIR, src_uri))
    repo_path = posixpath.normpath(posixpath.join(page_dir, target))
    if repo_path.startswith(".."):
        return match.group(0)
    inside = repo_path == DOCS_DIR or repo_path.startswith(f"{DOCS_DIR}/")
    path = repo_root / repo_path
    if inside and (
        site_files is None or path.is_dir() or repo_path[len(DOCS_DIR) + 1 :] in site_files
    ):
        return match.group(0)
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
        files: The mkdocs file collection; links to existing files it does not contain
            (``exclude_docs``) point at GitHub instead of a dead page.

    Returns:
        The rewritten page source.
    """
    repo_root = Path(str(config["config_file_path"])).resolve().parent
    site_files = frozenset(str(f.src_uri) for f in files)
    return rewrite_outside_links(markdown, str(page.file.src_uri), repo_root, site_files)

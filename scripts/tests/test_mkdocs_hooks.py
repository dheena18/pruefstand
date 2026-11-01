"""The mkdocs hook turns existing outside-docs links into GitHub URLs and leaves the rest (T0.4)."""

from pathlib import Path

import pytest
from mkdocs_hooks import REPO_URL, rewrite_outside_links


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "T1.1-x.md").write_text("x", encoding="utf-8")
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "TASKS.md").write_text("x", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    return tmp_path


def test_stub_page_link_to_an_existing_prompt(repo: Path) -> None:
    out = rewrite_outside_links("[a](../../prompts/T1.1-x.md#top)", "_external/prompts.md", repo)
    assert out == f"[a]({REPO_URL}/blob/main/prompts/T1.1-x.md#top)"


def test_docs_page_link_and_directory_target(repo: Path) -> None:
    text = "[t](../../tasks/TASKS.md) [d](../../prompts/)"
    out = rewrite_outside_links(text, "engineering/README.md", repo)
    assert f"({REPO_URL}/blob/main/tasks/TASKS.md)" in out
    assert f"({REPO_URL}/tree/main/prompts)" in out


def test_missing_targets_stay_broken_so_strict_mode_reports_them(repo: Path) -> None:
    text = "[a](../../prompts/missing.md)"
    assert rewrite_outside_links(text, "_external/prompts.md", repo) == text


@pytest.mark.parametrize(
    "link", ["[a](other.md)", "[a](#anchor)", "[a](https://x.org/a.md)", "[a](../spec/SPEC.md)"]
)
def test_links_inside_docs_and_external_links_are_untouched(repo: Path, link: str) -> None:
    assert rewrite_outside_links(link, "engineering/README.md", repo) == link


def test_code_fences_are_untouched(repo: Path) -> None:
    text = "```\n[a](../../tasks/TASKS.md)\n```"
    assert rewrite_outside_links(text, "engineering/README.md", repo) == text


def test_inline_code_spans_are_untouched(repo: Path) -> None:
    text = "`[a](../../tasks/TASKS.md)` and [t](../../tasks/TASKS.md)"
    out = rewrite_outside_links(text, "engineering/README.md", repo)
    assert out.startswith("`[a](../../tasks/TASKS.md)` and ")
    assert f"({REPO_URL}/blob/main/tasks/TASKS.md)" in out


def test_links_to_excluded_docs_files_point_at_github(repo: Path) -> None:
    (repo / "docs" / "ops").mkdir()
    (repo / "docs" / "ops" / "setup-log.md").write_text("x", encoding="utf-8")
    (repo / "docs" / "kept.md").write_text("x", encoding="utf-8")
    site = frozenset({"kept.md"})
    text = "[a](ops/setup-log.md#s1) [b](kept.md)"
    out = rewrite_outside_links(text, "index.md", repo, site)
    assert out == f"[a]({REPO_URL}/blob/main/docs/ops/setup-log.md#s1) [b](kept.md)"
    assert rewrite_outside_links(text, "index.md", repo) == text

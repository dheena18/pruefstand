"""GitHubPublisher hardening: input validation, pinned API host, redirects, page cap."""

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx

from pruefstand.core.errors import PruefstandError
from pruefstand.report import github
from pruefstand.report.github import GitHubPublisher

API = "https://api.github.com"
REPO = "dheena18/pruefstand"
TOKEN = "ghs_SECRETTOKEN123456"  # noqa: S105  (test value)
SHA = "d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8091a2b3c4d"
MARKER = "<!-- pruefstand:pr-comment -->"


@pytest.fixture
def mock() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=API, assert_all_called=False) as router:
        yield router


def _pub(**kw: Any) -> GitHubPublisher:
    return GitHubPublisher(TOKEN, REPO, **kw)


def _comments(mock: respx.MockRouter, pages: list[list[dict[str, Any]]]) -> respx.Route:
    def side(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(200, json=pages[page - 1] if page <= len(pages) else [])

    return mock.get(f"/repos/{REPO}/issues/7/comments").mock(side_effect=side)


def _c(cid: int, login: str, body: str) -> dict[str, Any]:
    return {"id": cid, "user": {"login": login}, "body": body}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(github, "_sleep", lambda _s: None)


@pytest.mark.parametrize("bad", ["a b", "tok\nen", ""])
def test_malformed_token_is_rejected_without_echo(bad: str) -> None:
    with pytest.raises(ValueError, match="token") as err:
        GitHubPublisher(bad, REPO)
    assert bad.strip() == "" or bad not in str(err.value)


@pytest.mark.parametrize("repo", ["a", "a/b/c", "a/../b", "a/b?x=1", "../x"])
def test_repo_must_be_owner_slash_name(repo: str) -> None:
    with pytest.raises(ValueError, match="repo"):
        GitHubPublisher(TOKEN, repo)


def test_rejects_bad_inputs_without_a_request(mock: respx.MockRouter) -> None:
    pub = _pub()
    with pytest.raises(ValueError, match="sha"):
        pub.post_status("../../x", "pending", "d")
    with pytest.raises(ValueError, match="marker"):
        pub.upsert_pr_comment(7, "body", "")
    with pytest.raises(ValueError, match="pr_number"):
        pub.upsert_pr_comment(0, MARKER, MARKER)
    with pytest.raises(ValueError, match="body"):
        pub.upsert_pr_comment(7, MARKER + "x" * 70_000, MARKER)
    assert not mock.calls


@pytest.mark.parametrize(
    "url",
    [
        "http://api.github.com",
        "https://evil.example",
        "https://api.github.com@evil.example",
        "https://user:pw@api.github.com",
        "https://api.github.com:8443",
        "https://api.github.com.evil.example",
    ],
)
def test_api_url_is_pinned(url: str) -> None:
    with pytest.raises(ValueError, match="api_url"):
        GitHubPublisher(TOKEN, REPO, url)


def test_enterprise_host_is_an_explicit_opt_in() -> None:
    pub = GitHubPublisher(
        TOKEN, REPO, "https://ghe.example.org/api/v3", enterprise_host="ghe.example.org"
    )
    assert "ghe.example.org" not in repr(pub) or REPO in repr(pub)
    with pytest.raises(ValueError, match="api_url"):
        GitHubPublisher(TOKEN, REPO, "https://other.example.org", enterprise_host="ghe.example.org")


def test_redirects_are_not_followed(mock: respx.MockRouter) -> None:
    mock.post(f"/repos/{REPO}/statuses/{SHA}").respond(
        302, headers={"location": "https://evil.example/x"}
    )
    target = mock.route(host="evil.example").respond(200)
    with pytest.raises(PruefstandError):
        _pub().post_status(SHA, "pending", "d")
    assert not target.called


def test_hitting_the_page_cap_warns_and_posts(
    mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(github, "MAX_PAGES", 2)
    mock.get("/user").respond(200, json={"login": "b"})
    page = [_c(i, "x", "y") for i in range(100)]
    _comments(mock, [page, page, page])
    mock.post(f"/repos/{REPO}/issues/7/comments").respond(201, json={"id": 9})
    warnings: list[str] = []
    monkeypatch.setattr(github.log, "warning", lambda event, **_k: warnings.append(event))
    assert _pub().upsert_pr_comment(7, MARKER, MARKER) == 9
    assert warnings == ["comment_search_page_cap"]

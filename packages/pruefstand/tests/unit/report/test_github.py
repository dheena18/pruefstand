"""``GitHubPublisher``: marker comment upsert, ``post_status`` and the ``set_check`` wrapper."""

import json
from collections.abc import Iterator
from typing import Any, Literal

import httpx
import pytest
import respx

from pruefstand.core.enums import GateStatus
from pruefstand.core.errors import PruefstandError
from pruefstand.report import github
from pruefstand.report.github import GitHubPublisher

API = "https://api.github.com"
REPO = "dheena18/pruefstand"
TOKEN = "ghs_SECRETTOKEN123456"  # noqa: S105  (test value)
SHA = "d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8091a2b3c4d"
MARKER = "<!-- pruefstand:pr-comment -->"
STATUS_URL = f"{API}/repos/{REPO}/statuses/{SHA}"
State = Literal["pending", "success", "failure", "error"]


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(github, "_sleep", lambda _s: None)


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


def test_posts_new_comment_when_none_exists(mock: respx.MockRouter) -> None:
    mock.get("/user").respond(200, json={"login": "pruefstand-bot[bot]"})
    _comments(mock, [[_c(1, "someone", "hello")]])
    post = mock.post(f"/repos/{REPO}/issues/7/comments").respond(201, json={"id": 99})
    assert _pub().upsert_pr_comment(7, f"{MARKER}\nbody", MARKER) == 99
    assert json.loads(post.calls.last.request.content) == {"body": f"{MARKER}\nbody"}


def test_patches_own_comment_found_on_page_two(mock: respx.MockRouter) -> None:
    mock.get("/user").respond(200, json={"login": "pruefstand-bot[bot]"})
    page1 = [_c(i, "other", "x") for i in range(1, 101)]
    _comments(mock, [page1, [_c(205, "pruefstand-bot[bot]", f"old\n{MARKER}")]])
    patch = mock.patch(f"/repos/{REPO}/issues/comments/205").respond(200, json={"id": 205})
    assert _pub().upsert_pr_comment(7, f"{MARKER}\nnew", MARKER) == 205
    assert patch.called


def test_user_403_assumes_github_actions_bot(mock: respx.MockRouter) -> None:
    user = mock.get("/user").respond(403, json={"message": "Resource not accessible"})
    _comments(mock, [[_c(5, "github-actions[bot]", MARKER)]])
    patch = mock.patch(f"/repos/{REPO}/issues/comments/5").respond(200, json={"id": 5})
    assert _pub().upsert_pr_comment(7, MARKER, MARKER) == 5
    assert patch.called
    assert user.call_count == 1


def test_bot_login_skips_the_user_lookup(mock: respx.MockRouter) -> None:
    user = mock.get("/user").respond(200, json={"login": "wrong"})
    _comments(mock, [[_c(6, "pruefstand-bot[bot]", MARKER)]])
    mock.patch(f"/repos/{REPO}/issues/comments/6").respond(200, json={"id": 6})
    assert _pub(bot_login="pruefstand-bot[bot]").upsert_pr_comment(7, MARKER, MARKER) == 6
    assert not user.called


def test_marker_comment_by_another_user_is_ignored(mock: respx.MockRouter) -> None:
    mock.get("/user").respond(200, json={"login": "pruefstand-bot[bot]"})
    _comments(mock, [[_c(3, "mallory", f"fake {MARKER}")]])
    patch = mock.patch(f"/repos/{REPO}/issues/comments/3").respond(200, json={"id": 3})
    mock.post(f"/repos/{REPO}/issues/7/comments").respond(201, json={"id": 11})
    assert _pub().upsert_pr_comment(7, MARKER, MARKER) == 11
    assert not patch.called


def test_user_is_looked_up_once_across_calls(mock: respx.MockRouter) -> None:
    user = mock.get("/user").respond(200, json={"login": "b"})
    _comments(mock, [[]])
    mock.post(f"/repos/{REPO}/issues/7/comments").respond(201, json={"id": 1})
    pub = _pub()
    pub.upsert_pr_comment(7, MARKER, MARKER)
    pub.upsert_pr_comment(7, MARKER, MARKER)
    assert user.call_count == 1


def test_patch_5xx_is_retried(mock: respx.MockRouter) -> None:
    mock.get("/user").respond(200, json={"login": "b"})
    _comments(mock, [[_c(4, "b", MARKER)]])
    patch = mock.patch(f"/repos/{REPO}/issues/comments/4").mock(
        side_effect=[httpx.Response(502), httpx.Response(502), httpx.Response(200, json={"id": 4})]
    )
    assert _pub().upsert_pr_comment(7, MARKER, MARKER) == 4
    assert patch.call_count == 3


def test_comment_post_is_never_retried(mock: respx.MockRouter) -> None:
    mock.get("/user").respond(200, json={"login": "b"})
    _comments(mock, [[]])
    post = mock.post(f"/repos/{REPO}/issues/7/comments").respond(502)
    with pytest.raises(PruefstandError):
        _pub().upsert_pr_comment(7, MARKER, MARKER)
    assert post.call_count == 1


def test_comment_post_transport_error_is_not_retried(mock: respx.MockRouter) -> None:
    mock.get("/user").respond(200, json={"login": "b"})
    _comments(mock, [[]])
    post = mock.post(f"/repos/{REPO}/issues/7/comments").mock(side_effect=httpx.ConnectError("x"))
    with pytest.raises(PruefstandError):
        _pub().upsert_pr_comment(7, MARKER, MARKER)
    assert post.call_count == 1


def test_5xx_gives_up_after_three_retries(mock: respx.MockRouter) -> None:
    route = mock.post(STATUS_URL.removeprefix(API)).respond(503)
    with pytest.raises(PruefstandError):
        _pub().post_status(SHA, "pending", "queued")
    assert route.call_count == 4


def test_401_raises_without_the_token(mock: respx.MockRouter) -> None:
    mock.get("/user").respond(401, json={"message": "Bad credentials"})
    with pytest.raises(PruefstandError) as err:
        _pub().upsert_pr_comment(7, MARKER, MARKER)
    assert TOKEN not in str(err.value)
    assert TOKEN not in repr(err.value.args)
    assert "Bad credentials" not in str(err.value)


def test_token_not_in_repr_and_authorization_header_sent(mock: respx.MockRouter) -> None:
    pub = _pub()
    assert TOKEN not in repr(pub)
    route = mock.post(STATUS_URL.removeprefix(API)).respond(201, json={})
    pub.post_status(SHA, "pending", "queued")
    assert route.calls.last.request.headers["authorization"] == f"Bearer {TOKEN}"


# --- post_status (R13 P4.2) -------------------------------------------------------------


def _sent(route: respx.Route) -> dict[str, Any]:
    assert route.call_count == 1
    return json.loads(route.calls.last.request.content)  # type: ignore[no-any-return]


def test_post_status_body_is_exact(mock: respx.MockRouter) -> None:
    route = mock.post(f"/repos/{REPO}/statuses/{SHA}").respond(201, json={})
    _pub().post_status(SHA, "pending", "queued")
    assert _sent(route) == {
        "state": "pending",
        "description": "queued",
        "context": "pruefstand/gate",
    }


def test_post_status_error_description_verbatim(mock: respx.MockRouter) -> None:
    route = mock.post(f"/repos/{REPO}/statuses/{SHA}").respond(201, json={})
    _pub().post_status(SHA, "error", "executor unhealthy: tunnel_lost")
    body = _sent(route)
    assert body["state"] == "error"
    assert body["description"] == "executor unhealthy: tunnel_lost"


def test_post_status_custom_context_and_truncation(mock: respx.MockRouter) -> None:
    route = mock.post(f"/repos/{REPO}/statuses/{SHA}").respond(201, json={})
    _pub().post_status(SHA, "success", "x" * 300, context="pruefstand/nightly")
    body = _sent(route)
    assert body["context"] == "pruefstand/nightly"
    assert body["description"] == "x" * 140


@pytest.mark.parametrize("state", ["neutral", "", "SUCCESS", "queued"])
def test_post_status_rejects_other_states_and_sends_nothing(
    mock: respx.MockRouter, state: str
) -> None:
    with pytest.raises(ValueError, match="state"):
        _pub().post_status(SHA, state, "d")  # type: ignore[arg-type]
    assert not mock.calls


def test_post_status_retries_5xx_then_succeeds(mock: respx.MockRouter) -> None:
    route = mock.post(f"/repos/{REPO}/statuses/{SHA}").mock(
        side_effect=[httpx.Response(500), httpx.Response(502), httpx.Response(201, json={})]
    )
    _pub().post_status(SHA, "success", "ok")
    assert route.call_count == 3


def test_post_status_401_has_no_token(mock: respx.MockRouter) -> None:
    mock.post(f"/repos/{REPO}/statuses/{SHA}").respond(401, json={"message": "Bad credentials"})
    with pytest.raises(PruefstandError) as err:
        _pub().post_status(SHA, "success", "ok")
    assert TOKEN not in str(err.value)


# --- set_check (interfaces §10 table) ----------------------------------------------------

G = GateStatus
TABLE: list[tuple[GateStatus, bool, State, str]] = [
    (G.PASS, False, "success", "PASS: all good"),
    (G.WARN, False, "success", "WARN: all good"),
    (G.INSUFFICIENT_DATA, False, "success", "INSUFFICIENT_DATA: all good"),
    (G.UNSUPPORTED_CONFIG, False, "success", "UNSUPPORTED_CONFIG: all good"),
    (G.FAIL, False, "failure", "FAIL: all good"),
    (G.FAIL, True, "failure", "FAIL: all good"),
    (G.PASS, True, "failure", "no baseline for all good; run baseline-promote"),
    (G.INSUFFICIENT_DATA, True, "failure", "no baseline for all good; run baseline-promote"),
    (G.WARN, True, "failure", "no baseline for all good; run baseline-promote"),
]


@pytest.mark.parametrize(("status", "no_baseline", "state", "description"), TABLE)
def test_set_check_maps_the_table_through_post_status(
    mock: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
    status: GateStatus,
    *,
    no_baseline: bool,
    state: str,
    description: str,
) -> None:
    route = mock.post(f"/repos/{REPO}/statuses/{SHA}").respond(201, json={})
    pub = _pub()
    spy: list[tuple[Any, ...]] = []
    original = pub.post_status

    def spied(*args: Any, **kwargs: Any) -> None:
        spy.append((args, kwargs))
        original(*args, **kwargs)

    monkeypatch.setattr(pub, "post_status", spied)
    pub.set_check(SHA, status, "all good", no_baseline=no_baseline)
    assert spy == [((SHA, state, description), {})]
    assert _sent(route) == {
        "state": state,
        "description": description,
        "context": "pruefstand/gate",
    }


def test_set_check_truncates_to_140(mock: respx.MockRouter) -> None:
    route = mock.post(f"/repos/{REPO}/statuses/{SHA}").respond(201, json={})
    _pub().set_check(SHA, G.PASS, "s" * 300)
    assert len(_sent(route)["description"]) == 140


@pytest.mark.parametrize("status", list(GateStatus))
@pytest.mark.parametrize("no_baseline", [False, True])
@pytest.mark.parametrize(
    "summary", ["ollama_down: x; retrying once", "tunnel_lost: x; re-dispatch to retry"]
)
def test_set_check_infra_error_overrides_everything(
    mock: respx.MockRouter, status: GateStatus, summary: str, *, no_baseline: bool
) -> None:
    route = mock.post(f"/repos/{REPO}/statuses/{SHA}").respond(201, json={})
    _pub().set_check(SHA, status, summary, no_baseline=no_baseline, infra_error=True)
    body = _sent(route)
    assert body["state"] == "error"
    assert body["description"] == f"executor infra error: {summary}"
    assert body["context"] == "pruefstand/gate"


def test_set_check_infra_error_truncates(mock: respx.MockRouter) -> None:
    route = mock.post(f"/repos/{REPO}/statuses/{SHA}").respond(201, json={})
    _pub().set_check(SHA, G.FAIL, "s" * 300, infra_error=True)
    assert len(_sent(route)["description"]) == 140

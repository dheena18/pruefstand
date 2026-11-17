"""github_read (D1095): pagination, renames, the 3000-file limit, 404, errors hide the token."""

import base64
import json

import httpx
import pytest
from gate_orchestrator.github_read import GitHubReadError, PublicRepo, status_of

TOKEN = "ghs_" + "x" * 36


def _repo(handler: httpx.MockTransport) -> PublicRepo:
    return PublicRepo(TOKEN, transport=handler)


def _files_handler(total: int) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        page = int(request.url.params["page"])
        start = (page - 1) * 100
        items = [{"filename": f"f{i}.py"} for i in range(start, min(start + 100, total))]
        if page == 1 and items:
            items[0]["previous_filename"] = ".github/workflows/old.yml"
        return httpx.Response(200, json=items)

    return httpx.MockTransport(handle)


def test_files_paginates_and_lists_both_sides_of_a_rename() -> None:
    paths = _repo(_files_handler(150)).files(7)
    assert len(paths) == 151
    assert ".github/workflows/old.yml" in paths


def test_files_at_the_3000_limit_is_refused() -> None:
    with pytest.raises(GitHubReadError, match="3000"):
        _repo(_files_handler(3000)).files(7)


def test_404_is_none_and_a_server_error_hides_the_token() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404 if "branches" in request.url.path else 500, json={})

    repo = _repo(httpx.MockTransport(handle))
    assert repo.branch_head("gate/pr-7") is None
    with pytest.raises(GitHubReadError) as err:
        repo.statuses("a" * 40)
    assert "HTTP 500" in str(err.value)
    assert TOKEN not in str(err.value)
    assert TOKEN not in repr(repo)


def test_statuses_file_at_and_pull() -> None:
    content = base64.b64encode(b"generator: {}\n").decode()

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/status"):
            return httpx.Response(
                200, json={"statuses": [{"context": "pruefstand/image", "state": "success"}]}
            )
        if "/contents/" in path:
            return httpx.Response(200, json={"encoding": "base64", "content": content})
        return httpx.Response(200, content=json.dumps({"number": 7}).encode())

    repo = _repo(httpx.MockTransport(handle))
    assert status_of(repo.statuses("a" * 40), "pruefstand/image") == {
        "context": "pruefstand/image",
        "state": "success",
    }
    assert repo.file_at("apps/rag-demo/configs/rag.gpu.yaml", "a" * 40) == "generator: {}\n"
    assert repo.pull(7)["number"] == 7


@pytest.mark.parametrize("token", ["", "a b", "x\n"])
def test_bad_token_is_refused(token: str) -> None:
    with pytest.raises(ValueError, match="invalid token"):
        PublicRepo(token)


def test_anonymous_reads_send_no_authorization_header() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert "Authorization" not in request.headers
        return httpx.Response(200, json={"commit": {"sha": "a" * 40}})

    assert PublicRepo(None, transport=httpx.MockTransport(handle)).branch_head("main") == "a" * 40


def test_redirects_are_not_followed() -> None:
    # review #224: a redirect would carry the reader elsewhere; it is an error instead
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.github.com"
        return httpx.Response(302, headers={"Location": "https://example.invalid/x"})

    with pytest.raises(GitHubReadError, match="HTTP 302"):
        _repo(httpx.MockTransport(handle)).statuses("a" * 40)

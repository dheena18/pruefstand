"""GitHub publisher: one editable PR comment and the commit status ``pruefstand/gate``.

The gate result goes out as a **commit status** (not a check run): ``post_status`` is the only
method that calls the statuses API, ``set_check`` maps a gate result onto it (interfaces §10,
R13 P4.2). The token only ever lives in the ``Authorization`` header of the HTTP client; it is
never logged, never part of an exception message and not shown by ``repr``.
"""

import re
import time
from typing import Any, Final, Literal, cast

import httpx

from pruefstand.core.enums import GateStatus
from pruefstand.core.errors import PruefstandError
from pruefstand.core.logging import get_logger

log = get_logger(__name__)

State = Literal["pending", "success", "failure", "error"]
_STATES: Final = frozenset({"pending", "success", "failure", "error"})
_REPO = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}")
_SHA = re.compile(r"[0-9a-fA-F]{7,64}")
_TOKEN = re.compile(r"[\x21-\x7e]{1,500}")
MAX_DESCRIPTION: Final = 140
MAX_BODY: Final = 65_000
MAX_MARKER: Final = 200
PAGE_SIZE: Final = 100
MAX_PAGES: Final = 100
RETRIES: Final = 3
TIMEOUT_S: Final = 10.0
DEFAULT_CONTEXT: Final = "pruefstand/gate"
ACTIONS_BOT: Final = "github-actions[bot]"
_BACKOFF_S: Final = (0.5, 1.0, 2.0)


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


class PublishError(PruefstandError):
    """A GitHub API call failed. The message holds the endpoint and status, never a secret."""


def truncate(text: str, limit: int = MAX_DESCRIPTION) -> str:
    """Cut ``text`` to ``limit`` characters (GitHub's status description limit)."""
    return text[:limit]


def status_for(
    status: GateStatus, summary: str, *, no_baseline: bool, infra_error: bool
) -> tuple[State, str]:
    """Map a gate result to ``(commit state, description)`` (interfaces §10 table).

    Args:
        status: The gate status.
        summary: One line; verbatim in the description (for ``no_baseline`` it is the
            ``eval_fingerprint``).
        no_baseline: The gate had no baseline: never a pass.
        infra_error: The run aborted on infrastructure: always ``error``.

    Returns:
        The state and the untruncated description.
    """
    if infra_error:
        return "error", f"executor infra error: {summary}"
    if status is GateStatus.FAIL:
        return "failure", f"FAIL: {summary}"
    if no_baseline:
        return "failure", f"no baseline for {summary}; run baseline-promote"
    return "success", f"{status.name}: {summary}"


class GitHubPublisher:
    """Edits the PR comment it owns and sets commit statuses.

    Args:
        token: Installation, ``GITHUB_TOKEN`` or fine-grained token. Never logged or echoed.
        repo: ``owner/name``.
        api_url: API base, ``https://api.github.com`` by default.
        bot_login: Login of the account the token acts as (an App's ``<slug>[bot]``). When
            unset, ``GET /user`` decides, and a 403 there (installation tokens) means
            ``github-actions[bot]``.

    Raises:
        ValueError: ``token``, ``repo`` or ``api_url`` is malformed.
    """

    def __init__(
        self,
        token: str,
        repo: str,
        api_url: str = "https://api.github.com",
        *,
        bot_login: str | None = None,
    ) -> None:
        if not _TOKEN.fullmatch(token):
            msg = "invalid token (empty, or contains white space or control characters)"
            raise ValueError(msg)
        if not _REPO.fullmatch(repo) or ".." in repo:
            msg = "repo must be '<owner>/<name>'"
            raise ValueError(msg)
        if not api_url.startswith("https://"):
            msg = "api_url must start with https://"
            raise ValueError(msg)
        self._repo = repo
        self._login = bot_login
        self._client = httpx.Client(
            base_url=api_url.rstrip("/"),
            timeout=TIMEOUT_S,
            follow_redirects=False,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "pruefstand",
            },
        )

    def __repr__(self) -> str:
        return f"GitHubPublisher(repo={self._repo!r})"

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:  # noqa: ANN401
        """Send a request; retry 5xx and transport errors up to ``RETRIES`` times."""
        for attempt in range(RETRIES + 1):
            try:
                response = self._client.request(method, path, **kwargs)
            except httpx.TransportError as exc:
                if attempt == RETRIES:
                    msg = f"GitHub API {method} {path}: {type(exc).__name__}"
                    raise PublishError(msg) from None
            else:
                if response.status_code < 500:
                    return response
                if attempt == RETRIES:
                    msg = f"GitHub API {method} {path}: HTTP {response.status_code}"
                    raise PublishError(msg)
            _sleep(_BACKOFF_S[min(attempt, len(_BACKOFF_S) - 1)])
        raise AssertionError  # pragma: no cover

    def _ok(self, method: str, path: str, **kwargs: Any) -> Any:  # noqa: ANN401
        """Return the JSON body of a 2xx answer, or raise ``PublishError`` (status code only)."""
        response = self._request(method, path, **kwargs)
        if not response.is_success:
            msg = f"GitHub API {method} {path}: HTTP {response.status_code}"
            raise PublishError(msg)
        return response.json() if response.content else None

    def _bot_login(self) -> str:
        if self._login is None:
            response = self._request("GET", "/user")
            if response.status_code == 403:
                self._login = ACTIONS_BOT
            elif response.is_success:
                self._login = str(response.json()["login"])
            else:
                msg = f"GitHub API GET /user: HTTP {response.status_code}"
                raise PublishError(msg)
        return self._login

    def _find_own_comment(self, pr_number: int, marker: str) -> int | None:
        login = self._bot_login()
        path = f"/repos/{self._repo}/issues/{pr_number}/comments"
        for page in range(1, MAX_PAGES + 1):
            items = cast(
                "list[dict[str, Any]]",
                self._ok("GET", path, params={"per_page": PAGE_SIZE, "page": page}),
            )
            for item in items:
                user = item.get("user") or {}
                if user.get("login") == login and marker in str(item.get("body", "")):
                    return int(item["id"])
            if len(items) < PAGE_SIZE:
                return None
        return None

    def upsert_pr_comment(self, pr_number: int, body: str, marker: str) -> int:
        """Edit the bot's own comment containing ``marker`` or post a new one.

        Args:
            pr_number: Pull request number.
            body: Comment body (at most 65 000 characters).
            marker: Hidden marker the body contains; comments of other users never match.

        Returns:
            The comment id.

        Raises:
            ValueError: ``pr_number``, ``marker`` or ``body`` is invalid (nothing is sent).
            PublishError: The API refused or kept failing.
        """
        if pr_number < 1:
            msg = "pr_number must be positive"
            raise ValueError(msg)
        if not marker or len(marker) > MAX_MARKER or "\n" in marker:
            msg = "marker must be one non-empty line of at most 200 characters"
            raise ValueError(msg)
        if len(body) > MAX_BODY:
            msg = f"body is longer than {MAX_BODY} characters"
            raise ValueError(msg)
        existing = self._find_own_comment(pr_number, marker)
        if existing is not None:
            data = self._ok(
                "PATCH", f"/repos/{self._repo}/issues/comments/{existing}", json={"body": body}
            )
        else:
            data = self._ok(
                "POST", f"/repos/{self._repo}/issues/{pr_number}/comments", json={"body": body}
            )
        return int(data["id"])

    def post_status(
        self, sha: str, state: State, description: str, context: str = DEFAULT_CONTEXT
    ) -> None:
        """Set a commit status (``POST /repos/{repo}/statuses/{sha}``): the only call to that API.

        Args:
            sha: Commit SHA (hex).
            state: ``pending``, ``success``, ``failure`` or ``error``.
            description: Truncated to 140 characters, otherwise sent verbatim.
            context: Status context, ``pruefstand/gate`` by default.

        Raises:
            ValueError: ``state``, ``sha`` or ``context`` is invalid (nothing is sent).
            PublishError: The API refused or kept failing.
        """
        if state not in _STATES:
            msg = "state must be one of pending, success, failure, error"
            raise ValueError(msg)
        if not _SHA.fullmatch(sha):
            msg = "sha must be a hex commit SHA"
            raise ValueError(msg)
        if not context or len(context) > MAX_MARKER:
            msg = "context must be 1 to 200 characters"
            raise ValueError(msg)
        body = {"state": state, "description": truncate(description), "context": context}
        self._ok("POST", f"/repos/{self._repo}/statuses/{sha}", json=body)
        log.info("commit_status_set", state=state, context=context)

    def set_check(
        self,
        sha: str,
        status: GateStatus,
        summary: str,
        *,
        no_baseline: bool = False,
        infra_error: bool = False,
    ) -> None:
        """Post a gate result as commit status ``pruefstand/gate`` (wrapper over ``post_status``).

        The mapping is the table of interfaces §10: ``infra_error`` wins over everything
        (``error``); ``FAIL`` is ``failure``; any other status with ``no_baseline`` is
        ``failure`` ("no baseline for <summary>; run baseline-promote", where the caller passes
        the ``eval_fingerprint`` as ``summary``); the rest is ``success`` with the status word.

        Args:
            sha: Commit SHA.
            status: The gate status.
            summary: One line, kept verbatim (the 140-character cut applies).
            no_baseline: ``GateReport.no_baseline``.
            infra_error: The run aborted with ``RunManifest.infra_error``.

        Raises:
            ValueError: ``sha`` is invalid.
            PublishError: The API refused or kept failing.
        """
        state, description = status_for(
            status, summary, no_baseline=no_baseline, infra_error=infra_error
        )
        self.post_status(sha, state, description)

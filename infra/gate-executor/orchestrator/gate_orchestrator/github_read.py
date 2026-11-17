"""Reads from the public repo that a dispatch needs (D1095): PR, changed files, statuses, refs.

The token is the per-job ``pruefstand-bot`` installation token (``PUBLIC_TOKEN``); it lives only in
the ``Authorization`` header of an ``httpx`` client pinned to ``https://api.github.com``. Every call
has a timeout; a non-2xx answer raises :class:`GitHubReadError` with the path and status code only.
"""

import base64
from collections.abc import Mapping
from typing import Any, cast

import httpx

from pruefstand.core.errors import PruefstandError

API = "https://api.github.com"
PUBLIC_REPO = "dheena18/pruefstand"
TIMEOUT_S = 30.0
FILES_LIMIT = 3000  # GitHub lists at most 3000 changed files per PR
Json = dict[str, Any]


class GitHubReadError(PruefstandError):
    """A GitHub read failed (path and HTTP status only, never the token or a body)."""


class PublicRepo:
    """Read-only view of the public repo for one dispatch."""

    def __init__(
        self,
        token: str | None,
        repo: str = PUBLIC_REPO,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Args: ``token`` (sent only to api.github.com; ``None`` = anonymous), ``repo``."""
        if token is not None and (not token or any(c.isspace() for c in token)):
            msg = "invalid token"
            raise ValueError(msg)
        auth = {} if token is None else {"Authorization": f"Bearer {token}"}  # None: anonymous
        self._repo = repo
        self._client = httpx.Client(
            base_url=API,
            timeout=TIMEOUT_S,
            follow_redirects=False,
            transport=transport,
            headers={
                **auth,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "pruefstand-executor",
            },
        )

    def __repr__(self) -> str:
        return f"PublicRepo(repo={self._repo!r})"

    def _get(self, path: str, params: Mapping[str, str | int] | None = None) -> Any:  # noqa: ANN401  (JSON)
        try:
            response = self._client.get(f"/repos/{self._repo}{path}", params=params)
        except httpx.TransportError as exc:
            msg = f"GitHub GET {path}: {type(exc).__name__}"
            raise GitHubReadError(msg) from None
        if response.status_code == 404:
            return None
        if not response.is_success:
            msg = f"GitHub GET {path}: HTTP {response.status_code}"
            raise GitHubReadError(msg)
        return response.json()

    def pull(self, number: int) -> Json:
        """``GET /pulls/{n}``.

        Raises:
            GitHubReadError: the PR does not exist or the call failed.
        """
        data = self._get(f"/pulls/{number}")
        if not isinstance(data, dict):
            msg = f"PR {number} not found"
            raise GitHubReadError(msg)
        return cast(Json, data)

    def files(self, number: int) -> list[str]:
        """Changed paths of PR ``number``; a renamed file contributes both its old and new path.

        Raises:
            GitHubReadError: the list is at GitHub's 3000-file limit (it may be truncated).
        """
        paths: list[str] = []
        listed = 0
        for page in range(1, FILES_LIMIT // 100 + 2):
            batch = self._get(f"/pulls/{number}/files", {"per_page": 100, "page": page}) or []
            listed += len(batch)
            for item in batch:
                paths.append(str(item.get("filename", "")))
                if item.get("previous_filename"):
                    paths.append(str(item["previous_filename"]))
            if len(batch) < 100:
                break
        if listed >= FILES_LIMIT:
            msg = f"PR {number} lists {FILES_LIMIT} files or more; the list may be truncated"
            raise GitHubReadError(msg)
        return paths

    def statuses(self, sha: str) -> list[Json]:
        """The latest status per context of ``sha`` (combined status)."""
        data = self._get(f"/commits/{sha}/status", {"per_page": 100}) or {}
        return [s for s in data.get("statuses", []) if isinstance(s, dict)]

    def branch_head(self, branch: str) -> str | None:
        """Head SHA of ``branch``, or ``None`` when it does not exist."""
        data = self._get(f"/branches/{branch}")
        return str(data["commit"]["sha"]) if isinstance(data, dict) else None

    def file_at(self, path: str, ref: str) -> str | None:
        """Text of ``path`` at ``ref`` (``None`` when absent)."""
        data = self._get(f"/contents/{path}", {"ref": ref})
        if not isinstance(data, dict) or data.get("encoding") != "base64":
            return None
        return base64.b64decode(str(data.get("content", ""))).decode("utf-8")


def status_of(statuses: list[Json], context: str) -> Json | None:
    """The status with ``context`` from :meth:`PublicRepo.statuses`, or ``None``."""
    return next((s for s in statuses if s.get("context") == context), None)

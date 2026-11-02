"""Publish sanitised run data to the public dashboard-data repository (T6.1 S9, W2.9, D300).

``push_dashboard_data`` checks the source first (no network), clones the repository shallow, adds
the run's files, rewrites the whole published tree with ``rewrite_tree`` and pushes ``main``.
``push_heartbeat`` force-pushes one commit with ``heartbeat.json`` to the branch ``heartbeat``.
The token reaches git only through ``GIT_ASKPASS``; no token of the private repo is involved.
"""

import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path

import httpx

from pruefstand.core.errors import StoreError
from pruefstand.core.logging import get_logger
from pruefstand.store._dashboard_src import Export, check_extra, load_export
from pruefstand.store._dashboard_tree import rewrite_tree
from pruefstand.store._git import Git, remote_url, valid_repo

_log = get_logger(__name__)
MAX_REPO_KB = 1024 * 1024
"""The data repository must stay below 1 GB (UI13-12)."""
_KEY = re.compile(r"[a-z][a-z0-9_]{0,63}")
_ATTEMPTS = 3
_SIZE_TIMEOUT_S = 10.0
_MAX_HEARTBEAT_KEYS = 64
_MAX_HEARTBEAT_VALUE = 1000


def check_repo_size(repo: str, token: str | None) -> None:
    """Fail when the data repository is above 1 GB; an unavailable size never blocks a push.

    Args:
        repo: ``owner/name``.
        token: Optional token for the API (sent as a header, never in a URL).

    Raises:
        StoreError: GitHub reports a size above ``MAX_REPO_KB`` (squash the repo, see the runbook).
    """
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = httpx.get(
            f"https://api.github.com/repos/{valid_repo(repo)}",
            headers=headers,
            timeout=_SIZE_TIMEOUT_S,
        )
        size = response.json().get("size") if response.status_code == httpx.codes.OK else None
    except (httpx.HTTPError, ValueError, AttributeError):
        size = None
    if not isinstance(size, int):
        _log.warning("dashboard_repo_size_unknown", repo=repo)
        return
    if size > MAX_REPO_KB:
        msg = f"{repo} is {size // 1024} MB, above 1 GB: squash it to an orphan commit (runbook)"
        raise StoreError(msg)


def _copy_export(work: Path, export: Export) -> None:
    runs = work / "runs" / export.run_id
    cases = work / "cases" / export.run_id
    for target in (runs, cases):
        if target.exists():
            shutil.rmtree(target)
    for name in export.files:
        relative = Path(name)
        if relative.parts[0] == "cases":
            target = cases / Path(*relative.parts[1:])
        else:
            target = runs / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(export.root / name, target)


def _clone_or_init(git: Git, url: str, branch: str, work: Path) -> None:
    listed = git.run("ls-remote", "--heads", url, f"refs/heads/{branch}")
    if listed.strip():
        git.run(
            "clone",
            "--quiet",
            "--depth",
            "1",
            "--single-branch",
            "--branch",
            branch,
            url,
            str(work),
        )
        return
    work.mkdir()
    git.run("init", "--quiet", str(work))
    git.run("symbolic-ref", "HEAD", f"refs/heads/{branch}", cwd=work)


def push_dashboard_data(
    src: Path,
    repo: str,
    *,
    token_env: str = "DASHBOARD_DATA_PAT",  # noqa: S107  (the NAME of a variable, not a secret)
    extra: Mapping[str, bytes] | None = None,
    remote: str | None = None,
) -> str:
    """Add a sanitised run to the dashboard-data repository and push ``main``.

    ``src`` is an export directory (``write_public_export``, extended and re-sealed with
    ``seal_export``): its files go to ``runs/<run_id>/`` and its ``cases/`` subdirectory to
    ``cases/<run_id>/``. The whole tree is then rewritten (merge-and-prune, D300):
    ``runs/index.json`` from every ``runs/*/run.json`` in the repository, the newest 200 runs,
    case shards and ``report.html`` for the newest 20, ``manifest.json`` with a SHA-256 per file.

    Args:
        src: The export directory; it is validated before any network access.
        repo: ``owner/pruefstand-dashboard-data``.
        token_env: Name of the environment variable that holds the fine-grained token of that
            repository only.
        extra: Further files by relative path (not under ``runs/`` or ``cases/``).
        remote: Git URL or local path overriding GitHub (tests; skips the size check).

    Returns:
        The sha of the pushed (or already present) commit.

    Raises:
        StoreError: The source was not produced by ``sanitise_run``, changed after sealing, holds a
            symlink or ``CANARY-``; an extra path is unsafe; the repository is above 1 GB; or git
            failed (after retries). Nothing is pushed in the first cases.
    """
    url = remote_url(repo, remote)
    export = load_export(src)
    files = check_extra(extra)
    if remote is None:
        check_repo_size(repo, os.environ.get(token_env))
    last: StoreError | None = None
    for attempt in range(_ATTEMPTS):
        try:
            return _publish(url, token_env, export, files, attempt)
        except StoreError as exc:
            last = exc
            _log.warning("dashboard_push_failed", attempt=attempt + 1, error=str(exc))
    msg = f"cannot push the dashboard data after {_ATTEMPTS} attempts: {last}"
    raise StoreError(msg) from last


def _publish(
    url: str, token_env: str, export: Export, files: dict[str, bytes], attempt: int
) -> str:
    with Git(token_env) as git, tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / f"work{attempt}"
        _clone_or_init(git, url, "main", work)
        _copy_export(work, export)
        for name, data in files.items():
            target = work / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        rewrite_tree(work)
        git.run("add", "--all", cwd=work)
        if git.run("status", "--porcelain", cwd=work).strip():
            git.run("commit", "--quiet", "-m", f"data: {export.run_id}", cwd=work, identity=True)
            git.run("push", "--quiet", url, "HEAD:refs/heads/main", cwd=work)
        return git.run("rev-parse", "HEAD", cwd=work).strip()


def push_heartbeat(
    repo: str,
    payload: Mapping[str, str],
    *,
    token_env: str = "DASHBOARD_DATA_PAT",  # noqa: S107  (the NAME of a variable, not a secret)
    remote: str | None = None,
) -> str:
    """Write ``heartbeat.json`` as the only commit of the branch ``heartbeat`` (force-pushed).

    The branch holds one commit, so the repository does not grow, and ``main`` is never touched
    (R9-21). The caller (the executor, every 15 minutes during a job) passes string values.

    Args:
        repo: ``owner/pruefstand-dashboard-data``.
        payload: Field name to string value (``ts``, ``tunnel_ok``, ``maintenance``, ...).
        token_env: Name of the environment variable that holds the token.
        remote: Git URL or local path overriding GitHub (tests).

    Returns:
        The sha of the new commit.

    Raises:
        StoreError: The payload is not a small mapping of snake_case names to strings, or git
            failed.
    """
    if len(payload) > _MAX_HEARTBEAT_KEYS:
        msg = f"heartbeat payload has more than {_MAX_HEARTBEAT_KEYS} fields"
        raise StoreError(msg)
    for key, value in payload.items():
        if _KEY.fullmatch(key) is None or not isinstance(value, str):
            msg = f"heartbeat payload field {key[:40]!r}: need a snake_case name, a string value"
            raise StoreError(msg)
        if len(value) > _MAX_HEARTBEAT_VALUE:
            msg = (
                f"heartbeat payload field {key!r} is longer than {_MAX_HEARTBEAT_VALUE} characters"
            )
            raise StoreError(msg)
    url = remote_url(repo, remote)
    text = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with Git(token_env) as git, tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "heartbeat"
        work.mkdir()
        git.run("init", "--quiet", str(work))
        git.run("symbolic-ref", "HEAD", "refs/heads/heartbeat", cwd=work)
        (work / "heartbeat.json").write_text(text, encoding="utf-8")
        git.run("add", "heartbeat.json", cwd=work)
        git.run("commit", "--quiet", "-m", "heartbeat", cwd=work, identity=True)
        git.run("push", "--quiet", "--force", url, "HEAD:refs/heads/heartbeat", cwd=work)
        return git.run("rev-parse", "HEAD", cwd=work).strip()


__all__ = ["MAX_REPO_KB", "check_repo_size", "push_dashboard_data", "push_heartbeat"]

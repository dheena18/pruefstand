"""``select_jobs``: what one owner dispatch of ``gate-executor.yml`` does (round 13 P1.2, D288).

Pure: the dispatch inputs and the public API responses (PR, changed files, the ``pruefstand/image``
status, the ``gate/pr-N`` head for forks) are injected. Outcomes:

* actor not in ``maintainers.txt`` → :class:`ConfigError` (exit 2, no status; defence in depth);
* no gated path changed → no job (``gate-router.yml`` owns that status, X2.2, P4.2);
* same-repo PR: the current head SHA; without a successful ``pruefstand/image`` status → ``pending``
  "awaiting signed image; dispatch again after build-images", else a ``gate`` job;
* fork PR (X2.3, D104): only when ``gate/pr-N`` head == fork head, a ``gate`` job on that SHA; else
  ``pending`` "fork head moved since mirroring; re-run mirror_fork_pr.sh" on the fork head.

``processed.jsonl`` is never consulted: a dispatch always runs (D288).
"""

from collections.abc import Mapping, Sequence
from importlib import resources

from gate_orchestrator.models import Dispatch, Job
from pruefstand.core.errors import ConfigError

AWAITING_IMAGE = "awaiting signed image; dispatch again after build-images"
FORK_MOVED = "fork head moved since mirroring; re-run mirror_fork_pr.sh"


def load_gated_paths() -> list[str]:
    """The ci-cd.md §5 gated-path list shipped as ``gated_paths.txt`` (one pattern per line)."""
    text = resources.files("gate_orchestrator").joinpath("gated_paths.txt").read_text("utf-8")
    return [line.strip() for line in text.splitlines() if line.strip()]


def matches(path: str, pattern: str) -> bool:
    """True when ``path`` matches ``pattern``: ``dir/**`` = anything below ``dir/``, else equality.

    >>> matches("apps/rag-demo/src/x.py", "apps/rag-demo/**")
    True
    >>> matches("apps/x/pyproject.toml", "pyproject.toml")
    False
    """
    if pattern.endswith("/**"):
        return path.startswith(pattern[:-2])
    return path == pattern


def touches_gated(files: Sequence[str], gated_paths: Sequence[str]) -> bool:
    """True when any changed file matches any gated pattern."""
    return any(matches(f, p) for f in files for p in gated_paths)


def _str_at(data: Mapping[str, object], *keys: str) -> str | None:
    node: object = data
    for key in keys:
        if not isinstance(node, Mapping):
            return None
        node = node.get(key)
    return node if isinstance(node, str) else None


def _image_ok(image_status: Mapping[str, object] | None) -> bool:
    return image_status is not None and image_status.get("state") == "success"


def select_jobs(
    dispatch: Dispatch,
    pr: Mapping[str, object],
    files: Sequence[str],
    image_status: Mapping[str, object] | None,
    gated_paths: Sequence[str],
    *,
    maintainers: frozenset[str],
    mirror_head: str | None,
) -> list[Job]:
    """Jobs for one dispatch (see the module docstring for the rules).

    Args:
        dispatch: the ``workflow_dispatch`` inputs (``pr``, actor, run id).
        pr: the public ``GET /repos/{o}/{r}/pulls/{n}`` response.
        files: the changed file paths (``pulls/{n}/files``, paginated).
        image_status: the ``pruefstand/image`` status on the target SHA, or ``None``.
        gated_paths: :func:`load_gated_paths`.
        maintainers: logins from ``maintainers.txt``.
        mirror_head: head SHA of branch ``gate/pr-N`` (forks), or ``None`` when not mirrored.

    Returns:
        ``[]`` (no gated path), one ``pending`` job, or one ``gate`` job (tier ``pr``).

    Raises:
        ConfigError: the actor is not a maintainer, or the PR data is not the dispatched PR.
    """
    if dispatch.actor not in maintainers:
        msg = f"dispatch by {dispatch.actor!r}: not in maintainers.txt"
        raise ConfigError(msg)
    head = _str_at(pr, "head", "sha")
    if pr.get("number") != dispatch.pr or head is None:
        msg = f"PR data does not belong to dispatched PR {dispatch.pr}"
        raise ConfigError(msg)
    if not touches_gated(files, gated_paths):
        return []
    base_repo = _str_at(pr, "base", "repo", "full_name")
    is_fork = _str_at(pr, "head", "repo", "full_name") != base_repo
    if is_fork and mirror_head != head:
        return [Job(kind="pending", sha=head, pr_number=dispatch.pr, tier="pr", reason=FORK_MOVED)]
    if not _image_ok(image_status):
        return [
            Job(kind="pending", sha=head, pr_number=dispatch.pr, tier="pr", reason=AWAITING_IMAGE)
        ]
    return [Job(kind="gate", sha=head, pr_number=dispatch.pr, tier="pr")]

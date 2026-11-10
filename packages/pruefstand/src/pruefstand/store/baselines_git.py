"""``GitBranchBaselineStore``: run files in the data root, only ``index.json`` in git (X2.7, D157).

The branch ``baselines`` of the private executor repository holds exactly ``baselines/index.json``:
per ``(fingerprint, ref)`` the ordered run ids and the SHA-256 of each ``manifest.json``. The run
files live under ``data_root`` in the layout of ``LocalDirBaselineStore``. ``get`` reads the index
from a shallow clone and verifies the files on disk against it; ``put`` renames the new baseline
into place first and pushes the index only after that, rolling the rename back if the push fails.
"""

import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from pruefstand.core.errors import StoreError, StoreIntegrityError
from pruefstand.core.logging import get_logger
from pruefstand.core.models.baseline import ExpectedBaseline, PromotionOverride
from pruefstand.core.models.run import RunArtifacts
from pruefstand.store._baseline_dir import read_baseline
from pruefstand.store._baseline_write import Clock, promote_to_disk, safe_rollback, utc_now
from pruefstand.store._git import Git, remote_url
from pruefstand.store._promote_lock import check_expected, promote_lock
from pruefstand.store.baseline_index import (
    BaselineIndex,
    read_index_file,
    reconcile_index,
    render_index,
    validate_fingerprint,
    validate_ref,
    with_promotion,
)
from pruefstand.store.promote import BaselineRefused
from pruefstand.store.retention import prune_baselines

_log = get_logger(__name__)
DEFAULT_TOKEN_ENV = "PRUEFSTAND_BASELINES_TOKEN"  # noqa: S105  (the NAME of a variable, not a secret)
INDEX_PATH = "baselines/index.json"
_ATTEMPTS = 3
SENTINEL = ".pruefstand-data-root"


class GitBranchBaselineStore:
    """Baselines whose index lives in a git branch (``baselines/index.json``).

    Args:
        repo: ``owner/name`` of the private executor repository.
        data_root: Directory with the run files (``<data_root>/<fingerprint>/<ref>/``); it must
            exist, so a missing mount can never look like "no baseline".
        branch: The index-only branch.
        remote: Git URL or local path overriding ``https://github.com/<repo>.git`` (tests).
        token_env: Name of the environment variable that holds the push token; may be unset.
        clock: Source of ``promoted_at``.
        require_sentinel: Also require ``<data_root>/../.pruefstand-data-root`` (set up by
            ``infra/vm/setup-data-root.sh``) so an unmounted data root is detected.

    Raises:
        StoreError: (constructor) ``repo`` is not ``owner/name``. No git command runs here.
    """

    def __init__(
        self,
        repo: str,
        data_root: Path,
        *,
        branch: str = "baselines",
        remote: str | None = None,
        token_env: str | None = DEFAULT_TOKEN_ENV,
        clock: Clock | None = None,
        require_sentinel: bool = False,
    ) -> None:
        self._url = remote_url(repo, remote)
        self._root = data_root
        self._branch = branch
        self._token_env = token_env
        self._clock = clock or utc_now
        self._sentinel = require_sentinel

    @property
    def root(self) -> Path:
        """The data root that holds the run files."""
        return self._root

    def get(self, eval_fingerprint: str, ref: str = "main") -> RunArtifacts | None:
        """Return the baseline pinned by the index, verified against the files on disk.

        Args:
            eval_fingerprint: The fingerprint.
            ref: One of the refs.

        Returns:
            The run, or None when the index has no baseline for ``(fingerprint, ref)``.

        Raises:
            StoreError: Unknown ref, a missing data root, a missing or invalid file, or git failed.
            StoreIntegrityError: A file or ``manifest.json`` differs from what was recorded.
        """
        validate_fingerprint(eval_fingerprint)
        validate_ref(ref)
        self._check_root()
        with Git(self._token_env) as git, tempfile.TemporaryDirectory() as tmp:
            index = self._fetch_index(git, Path(tmp) / "clone")[0]
        runs = index.entries.get(eval_fingerprint, {}).get(ref)
        if runs is None or not runs.runs:
            return None
        entry = runs.runs[-1]
        art = read_baseline(
            self._root, eval_fingerprint, ref, expected_manifest_sha256=entry.manifest_sha256
        )
        if art is None:
            msg = f"the index lists {eval_fingerprint}/{ref} but {self._root} has no such baseline"
            raise StoreError(msg)
        if art.results.manifest.run_id != entry.run_id:
            msg = f"the baseline in {eval_fingerprint}/{ref} is not the run the index names"
            raise StoreIntegrityError(msg)
        return art

    def put(
        self,
        run: RunArtifacts,
        ref: str = "main",
        *,
        override: PromotionOverride | None = None,
        expected: ExpectedBaseline | None = None,
    ) -> None:
        """Store ``run``: files first (write-then-rename), then one index commit.

        If the index cannot be pushed the data root is rolled back to the previous baseline.

        Raises:
            BaselineRefused: The run is incomplete or flagged.
            StoreError: Unknown ref, a missing data root, a failed write, or a failed push.
        """
        self._check_root()
        with promote_lock(self._root):
            promotion = promote_to_disk(self._root, run, ref, self._clock, override=override)
            entry, where = promotion.entry, f"{promotion.fingerprint}/{ref}"

            def add(index: BaselineIndex) -> BaselineIndex:
                runs = index.entries.get(promotion.fingerprint, {}).get(ref)
                current = runs.runs[-1].run_id if runs is not None and runs.runs else None
                if current == entry.run_id:
                    return index  # an earlier attempt reached the remote: idempotent retry
                check_expected(current, expected, where)  # re-checked on every fresh index
                return with_promotion(index, promotion.fingerprint, ref, entry)

            try:
                self._publish(add, f"promote {where} {entry.run_id}")
            except BaseException:
                safe_rollback(promotion)
                raise
            promotion.commit()

    def prune(self, *, keep: int = 20, unused_days: int = 90, now: datetime) -> list[str]:
        """Prune the data root, then drop the removed runs from the index in one commit.

        Args:
            keep: History entries per fingerprint.
            unused_days: Age after which a fingerprint is unused (release anchors stay).
            now: The current time (timezone-aware).

        Returns:
            The deleted paths relative to the data root.
        """
        self._check_root()
        removed = prune_baselines(self._root, keep=keep, unused_days=unused_days, now=now)
        if removed:
            self._publish(lambda index: reconcile_index(index, self._root), "prune")
        return removed

    def _check_root(self) -> None:
        if not self._root.is_dir():
            msg = f"data root {self._root} is missing or not a directory"
            raise StoreError(msg)
        if self._sentinel and not (self._root.parent / SENTINEL).is_file():
            msg = f"data root sentinel {SENTINEL} is missing next to {self._root}: not mounted?"
            raise StoreError(msg)

    def _fetch_index(self, git: Git, clone: Path) -> tuple[BaselineIndex, bool]:
        """Return the index of the remote branch and whether the branch exists.

        The branch holds one small file, so a depth-1 blob-less single-branch clone is enough.
        """
        listed = git.run("ls-remote", "--heads", self._url, f"refs/heads/{self._branch}")
        if not listed.strip():
            return BaselineIndex.empty(), False
        git.run(
            "clone", "--quiet", "--depth", "1", "--filter=blob:none", "--single-branch",
            "--branch", self._branch, self._url, str(clone),
        )  # fmt: skip
        return read_index_file(clone / INDEX_PATH), True

    def _publish(self, change: Callable[[BaselineIndex], BaselineIndex], message: str) -> None:
        """Apply ``change`` to the index, commit and push; retry with a fresh clone."""
        last: StoreError | None = None
        for attempt in range(_ATTEMPTS):
            with Git(self._token_env) as git, tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp) / "work"
                try:
                    index, exists = self._fetch_index(git, work)
                    if not exists:
                        self._init_branch(git, work)
                    changed = change(index)
                    if exists and changed == index:
                        return
                    target = work / INDEX_PATH
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(render_index(changed))
                    git.run("add", "--all", cwd=work)
                    git.run(
                        "commit", "--quiet", "-m", f"baselines: {message}", cwd=work, identity=True
                    )
                    git.run(
                        "push", "--quiet", self._url, f"HEAD:refs/heads/{self._branch}", cwd=work
                    )
                except BaselineRefused:
                    raise  # a changed baseline is a verdict, not a transient push failure
                except StoreError as exc:
                    last = exc
                    _log.warning("baseline_index_push_failed", attempt=attempt + 1, error=str(exc))
                else:
                    return
        msg = f"cannot push the baseline index after {_ATTEMPTS} attempts: {last}"
        raise StoreError(msg) from last

    def _init_branch(self, git: Git, work: Path) -> None:
        work.mkdir()
        git.run("init", "--quiet", str(work))
        git.run("symbolic-ref", "HEAD", f"refs/heads/{self._branch}", cwd=work)

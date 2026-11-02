"""``LocalDirBaselineStore``: baselines as plain directories under one path (T6.1 S4).

The same layout as the data root of the git-backed store, so a restored data root can be read by
this class (restore drill, R9-17). There is no index: the current baseline is the one in
``<fingerprint>/<ref>/``, verified against its own ``manifest.json`` and ``run.json``.
"""

from datetime import datetime
from pathlib import Path

from pruefstand.core.models.run import RunArtifacts
from pruefstand.store._baseline_dir import read_baseline
from pruefstand.store._baseline_write import Clock, promote_to_disk, utc_now
from pruefstand.store.retention import prune_baselines


class LocalDirBaselineStore:
    """Baselines under ``path`` (``<path>/<eval_fingerprint>/<ref>/``).

    Args:
        path: The directory; created on the first ``put``.
        clock: Source of ``promoted_at`` (default: the current UTC time).
    """

    def __init__(self, path: Path, *, clock: Clock | None = None) -> None:
        self._root = path
        self._clock = clock or utc_now

    @property
    def root(self) -> Path:
        """The directory that holds the fingerprints."""
        return self._root

    def get(self, eval_fingerprint: str, ref: str = "main") -> RunArtifacts | None:
        """Return the verified baseline of ``(eval_fingerprint, ref)``, or None.

        Raises:
            StoreError: Unsafe names, an unknown ref, a symlink, or an invalid baseline.
            StoreIntegrityError: A file does not match its recorded SHA-256.
        """
        return read_baseline(self._root, eval_fingerprint, ref)

    def put(self, run: RunArtifacts, ref: str = "main") -> None:
        """Store ``run`` as the baseline of its fingerprint and ``ref``, atomically.

        The previous baseline stays readable until the new one is renamed into place and is kept
        in ``history/`` (one directory per promotion).

        Raises:
            BaselineRefused: The run is incomplete or flagged (judge fallback, drift, ...).
            StoreError: Unknown ref, unsafe names, a block that does not fit the ref, or a failed
                write (the previous baseline is intact then).
        """
        self._root.mkdir(parents=True, exist_ok=True)
        promotion = promote_to_disk(self._root, run, ref, self._clock)
        promotion.commit()

    def prune(self, *, keep: int = 20, unused_days: int = 90, now: datetime) -> list[str]:
        """Delete old history directories and unused fingerprints (see ``prune_baselines``)."""
        return prune_baselines(self._root, keep=keep, unused_days=unused_days, now=now)

"""``prune_baselines``: the last N baselines per fingerprint, unused fingerprints (W2.11, D110)."""

from datetime import datetime, timedelta
from pathlib import Path

from pruefstand.core.errors import StoreError
from pruefstand.core.logging import get_logger
from pruefstand.store._baseline_dir import read_baseline_manifest, real_dir, remove_tree
from pruefstand.store.baseline_index import REFS, validate_fingerprint, validate_run_id

_log = get_logger(__name__)
_ANCHORS = ("main", *(ref for ref in REFS if ref.startswith("release-")))


def prune_baselines(
    store_root: Path, *, keep: int = 20, unused_days: int = 90, now: datetime
) -> list[str]:
    """Keep the last ``keep`` history entries per fingerprint and drop unused fingerprints.

    Per fingerprint the newest ``keep`` ``history/<run_id>`` directories stay (by ``promoted_at``,
    then run id), plus the history entry of every current baseline. A fingerprint with no
    promotion for more than ``unused_days`` days loses everything except its ``main`` and
    ``release-b<k>`` baselines (the PR comparison and the drift anchors). Names that are not safe
    fingerprints, run ids or refs, symlinks and files are never followed, read or deleted. Prune
    twice and the second run removes nothing.

    Args:
        store_root: The data root (``<root>/<fingerprint>/...``).
        keep: History entries to keep per fingerprint, at least 1.
        unused_days: Age in days after which a fingerprint is unused.
        now: The current time (timezone-aware; there is no clock inside).

    Returns:
        The deleted paths relative to ``store_root``, e.g. ``<fp>/history/<run_id>``.

    Raises:
        StoreError: ``store_root`` is not a directory, ``keep`` < 1, or ``now`` is naive.
    """
    if keep < 1:
        msg = "keep must be at least 1"
        raise StoreError(msg)
    if now.tzinfo is None:
        msg = "now must carry a timezone"
        raise StoreError(msg)
    if not store_root.is_dir():
        msg = f"data root {store_root} is not a directory"
        raise StoreError(msg)
    removed: list[str] = []
    for entry in sorted(store_root.iterdir()):
        try:
            validate_fingerprint(entry.name)
            real_dir(entry)
        except StoreError:
            continue
        removed += _prune_fingerprint(
            store_root, entry.name, keep, timedelta(days=unused_days), now
        )
    return removed


def _promoted(directory: Path) -> datetime | None:
    try:
        return read_baseline_manifest(directory).promoted_at
    except StoreError as exc:
        _log.warning("baseline_manifest_unreadable", directory=directory.name, error=str(exc))
        return None


def _refs(base: Path) -> dict[str, Path]:
    return {ref: base / ref for ref in REFS if real_dir(base / ref, missing_ok=True)}


def _prune_fingerprint(
    root: Path, fingerprint: str, keep: int, unused: timedelta, now: datetime
) -> list[str]:
    base = root / fingerprint
    refs = _refs(base)
    history = _history(base)
    stamps = [_promoted(path) for path in refs.values()] + [h[0] for h in history]
    known = [t for t in stamps if t is not None]
    removed: list[str] = []
    if known and len(known) == len(stamps) and now - max(known) > unused:
        removed = _drop_unused(base, fingerprint)
        if not base.exists():
            return removed
        refs, history = _refs(base), _history(base)
    pinned = {_run_id(path) for path in refs.values()}
    excess = sorted(history, key=lambda h: (h[0] or now, h[1]))[: max(len(history) - keep, 0)]
    for _, run_id, path in excess:
        if run_id in pinned:
            continue
        remove_tree(path)
        removed.append(f"{fingerprint}/history/{run_id}")
    return removed


def _run_id(directory: Path) -> str | None:
    try:
        return read_baseline_manifest(directory).run_id
    except StoreError:
        return None


def _history(base: Path) -> list[tuple[datetime | None, str, Path]]:
    directory = base / "history"
    if not real_dir(directory, missing_ok=True):
        return []
    found = []
    for path in directory.iterdir():
        try:
            validate_run_id(path.name)
            real_dir(path)
        except StoreError:
            continue
        found.append((_promoted(path), path.name, path))
    return found


def _drop_unused(base: Path, fingerprint: str) -> list[str]:
    anchors = [name for name in _ANCHORS if real_dir(base / name, missing_ok=True)]
    if not anchors:
        remove_tree(base)
        return [fingerprint]
    removed = []
    for path in sorted(base.iterdir()):
        if path.name in (*anchors, "history") or path.is_symlink() or not path.is_dir():
            continue
        remove_tree(path)
        removed.append(f"{fingerprint}/{path.name}")
    return removed

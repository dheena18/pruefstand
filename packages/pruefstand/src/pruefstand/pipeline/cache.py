"""The target-response cache of a job: shared for main and nightly, an overlay for PRs (T6.1 S3).

``PRUEFSTAND_CACHE_MODE`` is ``overlay`` (default) or ``shared`` (ADR-0006, cache trust domains).
In ``overlay`` mode a PR job reads main's cache read-only and writes into a per-job temporary
directory that is deleted afterwards, so a PR can never poison the shared cache. A cache that
cannot be opened means "no cache", never a failed run.
"""

import os
import shutil
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from pruefstand.core.errors import ConfigError, StoreError
from pruefstand.core.logging import get_logger
from pruefstand.core.protocols import KVCache
from pruefstand.store.kv import CacheMode, DiskKVCache, build_cache

_log = get_logger(__name__)
_MODES: tuple[CacheMode, ...] = ("overlay", "shared")


def cache_mode(env: Mapping[str, str]) -> CacheMode:
    """The cache mode from ``PRUEFSTAND_CACHE_MODE`` (unset or empty: ``overlay``).

    Raises:
        ConfigError: The variable holds anything but ``shared`` or ``overlay``.

    Examples:
        >>> cache_mode({})
        'overlay'
        >>> cache_mode({"PRUEFSTAND_CACHE_MODE": "shared"})
        'shared'
    """
    value = env.get("PRUEFSTAND_CACHE_MODE") or "overlay"
    for mode in _MODES:
        if value == mode:
            return mode
    msg = f"PRUEFSTAND_CACHE_MODE={value[:20]!r}: must be 'shared' or 'overlay'"
    raise ConfigError(msg)


def shared_cache_dir(env: Mapping[str, str]) -> Path:
    """``PRUEFSTAND_CACHE_DIR``, else ``$PRUEFSTAND_HOME/cache`` (default home ``~/pruefstand``)."""
    named = env.get("PRUEFSTAND_CACHE_DIR")
    if named:
        return Path(named).expanduser()
    return Path(env.get("PRUEFSTAND_HOME") or "~/pruefstand").expanduser() / "cache"


@contextmanager
def target_cache(env: Mapping[str, str] | None = None) -> Iterator[KVCache | None]:
    """Open the target cache of this job and close it (and delete the overlay) afterwards.

    Args:
        env: Environment; default ``os.environ``.

    Yields:
        The cache, or None when it cannot be opened (the run then continues without one).

    Raises:
        ConfigError: ``PRUEFSTAND_CACHE_MODE`` is invalid.
    """
    values = os.environ if env is None else env
    mode = cache_mode(values)
    shared = shared_cache_dir(values)
    overlay = tempfile.mkdtemp(prefix="pruefstand-overlay-") if mode == "overlay" else None
    cache: KVCache | None = None
    try:
        cache = _open(mode, shared, Path(overlay) if overlay else None)
        yield cache
    finally:
        closer = getattr(cache, "close", None)
        if callable(closer):
            closer()
        if overlay is not None:
            shutil.rmtree(overlay, ignore_errors=True)


def _open(mode: CacheMode, shared: Path, overlay: Path | None) -> KVCache | None:
    try:
        return build_cache(mode, shared, overlay or shared)
    except StoreError as exc:
        _log.warning("target_cache_unavailable", mode=mode, error=str(exc))
    if overlay is None:
        return None
    try:  # main's cache is unreadable: the PR still gets a working cache of its own
        return DiskKVCache(overlay, "target")
    except StoreError as exc:
        _log.warning("target_cache_overlay_unavailable", error=str(exc))
        return None

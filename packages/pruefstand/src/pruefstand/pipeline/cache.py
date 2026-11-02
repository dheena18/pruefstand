"""The target-response cache of a job: shared for main and nightly, an overlay for PRs (T6.1 S3).

``PRUEFSTAND_CACHE_MODE`` is ``overlay`` (default) or ``shared`` (ADR-0006, cache trust domains).
In ``overlay`` mode a PR job reads main's cache read-only and writes into a per-job temporary
directory that is deleted afterwards, so a PR can never poison the shared cache. A cache that
cannot be opened means "no cache", never a failed run.
"""

import os
import re
import shutil
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from pruefstand.core.errors import ConfigError, StoreError
from pruefstand.core.logging import get_logger
from pruefstand.core.models.target import TargetInfo
from pruefstand.core.protocols import KVCache
from pruefstand.store.kv import CacheMode, DiskKVCache, build_cache

_log = get_logger(__name__)
_MODES: tuple[CacheMode, ...] = ("overlay", "shared")
_TRUSTED_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9:._@/+-]{0,199}")
UNKNOWN_SHA = ("", "unknown")


def trusted_target_id(env: Mapping[str, str]) -> str | None:
    """The identity of the candidate that the *executor* vouches for, or None.

    ``PRUEFSTAND_TRUSTED_TARGET_ID`` is the image digest the executor pulled. When set it goes into
    the cache key and into ``target_fingerprint``; what the target reports about itself can only
    add to it. Without it a PR job never reads main's cache.

    Raises:
        ConfigError: The value is not a plausible digest or id.
    """
    value = env.get("PRUEFSTAND_TRUSTED_TARGET_ID")
    if not value:
        return None
    if _TRUSTED_ID.fullmatch(value) is None:
        msg = (
            "PRUEFSTAND_TRUSTED_TARGET_ID: expected an image digest or id (1..200 safe characters)"
        )
        raise ConfigError(msg)
    return value


_PLACEHOLDERS = frozenset({"", "unknown", "none", "empty", "dev", "latest"})


def _placeholder(value: str | None) -> bool:
    """A missing value, a known placeholder, or all-zero hex (``0000000``, ``sha256:00..``)."""
    text = (value or "").strip().lower().removeprefix("sha256:")
    return text in _PLACEHOLDERS or re.fullmatch(r"0+", text) is not None


def identity_is_opaque(info: TargetInfo | None) -> bool:
    """True when the target reports no usable identity.

    That is: no ``/v1/info``, or a git sha and an image digest that are both placeholders
    (compared after ``strip().lower()``: empty, ``unknown``, ``none``, ``empty``, ``dev``,
    ``latest``, all-zero hex). Every build without the build arguments would share one
    fingerprint, so its answers are neither read from nor written to any cache.
    """
    return info is None or (_placeholder(info.git_sha) and _placeholder(info.image_digest))


def reads_base(*, usable: bool, trusted: str | None) -> bool:
    """Whether a PR job may read main's cache: a usable identity that the executor vouches for."""
    return usable and trusted is not None


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
def target_cache(
    env: Mapping[str, str] | None = None, *, enabled: bool = True, use_base: bool = True
) -> Iterator[KVCache | None]:
    """Open the target cache of this job and close it (and delete the overlay) afterwards.

    Args:
        env: Environment; default ``os.environ``.
        enabled: False yields None (opaque target identity: no cache at all).
        use_base: In ``overlay`` mode False keeps main's shared cache out entirely (no trusted
            target id: the candidate's own claims must never select main's answers).

    Yields:
        The cache, or None when it cannot be opened (the run then continues without one).

    Raises:
        ConfigError: ``PRUEFSTAND_CACHE_MODE`` is invalid.
    """
    values = os.environ if env is None else env
    mode = cache_mode(values)
    if not enabled:
        yield None
        return
    shared = shared_cache_dir(values)
    overlay = tempfile.mkdtemp(prefix="pruefstand-overlay-") if mode == "overlay" else None
    cache: KVCache | None = None
    try:
        cache = _open(mode, shared, Path(overlay) if overlay else None, use_base=use_base)
        yield cache
    finally:
        closer = getattr(cache, "close", None)
        if callable(closer):
            closer()
        if overlay is not None:
            shutil.rmtree(overlay, ignore_errors=True)


def _open(mode: CacheMode, shared: Path, overlay: Path | None, *, use_base: bool) -> KVCache | None:
    if overlay is not None and not use_base:
        return _own_overlay(overlay)
    try:
        return build_cache(mode, shared, overlay or shared)
    except StoreError as exc:
        _log.warning("target_cache_unavailable", mode=mode, error=str(exc))
    return None if overlay is None else _own_overlay(overlay)


def _own_overlay(overlay: Path) -> KVCache | None:
    try:  # the PR's per-job cache only; main's cache is not (or cannot be) read
        return DiskKVCache(overlay, "target")
    except StoreError as exc:
        _log.warning("target_cache_overlay_unavailable", error=str(exc))
        return None

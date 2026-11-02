"""``DiskKVCache``: the persistent byte cache behind the ``target`` and ``llm`` namespaces.

Backed by one SQLite file per namespace (stdlib ``sqlite3``). Values are stored as opaque BLOBs
and returned as bytes; nothing is ever unpickled (D365).
"""

import sqlite3
import threading
from pathlib import Path
from types import TracebackType
from typing import Literal, Self

from pruefstand.core.errors import StoreError
from pruefstand.core.protocols import KVCache

_FILE = "cache.sqlite3"
_BUSY_TIMEOUT_S = 2.0
MAX_KEY_CHARS = 512
"""Longest cache key (callers pass 16-character ``stable_hash`` digests)."""
MAX_VALUE_BYTES = 16 * 1024 * 1024
"""Largest value ``set`` stores; a bigger row found on read is treated as a miss."""
_NAMESPACES = frozenset({"target", "llm"})
CacheMode = Literal["shared", "overlay"]
"""``shared``: one writable cache (main, nightly). ``overlay``: PR jobs (cache trust domains)."""


class DiskKVCache:
    """A ``KVCache`` on ``<directory>/<namespace>/cache.sqlite3`` (decision D75).

    Keys are opaque strings (callers pass ``stable_hash`` output); values are bytes. In
    ``read_only`` mode (PR jobs) ``get`` works and ``set`` raises; a missing cache is empty and
    is not created.

    Args:
        directory: Cache root; each namespace lives in its own subdirectory.
        namespace: ``"target"`` (runner, target responses) or ``"llm"`` (``LLMClient``, T5.1).
        read_only: Refuse writes (the file is opened read-only).

    Raises:
        StoreError: (constructor) the cache file cannot be opened, is locked, or is not a
            database. Callers (T1.10) must treat that as "no cache" and continue without one.
    """

    def __init__(
        self, directory: Path, namespace: Literal["target", "llm"], *, read_only: bool = False
    ) -> None:
        if namespace not in _NAMESPACES:
            msg = f"unknown cache namespace {namespace!r}; use one of {sorted(_NAMESPACES)}"
            raise StoreError(msg)
        self._read_only = read_only
        self._closed = False
        self._lock = threading.Lock()  # one connection shared with worker threads (to_thread)
        self._db: sqlite3.Connection | None = None
        path = directory / namespace / _FILE
        if read_only and not path.exists():
            return
        try:
            if read_only:
                self._db = sqlite3.connect(
                    f"{path.resolve().as_uri()}?mode=ro",
                    uri=True,
                    timeout=_BUSY_TIMEOUT_S,
                    check_same_thread=False,
                )
                self._db.execute("PRAGMA query_only = ON")
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                self._db = sqlite3.connect(path, timeout=_BUSY_TIMEOUT_S, check_same_thread=False)
                self._db.execute(
                    "CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value BLOB NOT NULL)"
                )
                self._db.commit()
            self._db.execute("SELECT 1 FROM kv LIMIT 1")
        except (OSError, sqlite3.Error) as exc:
            self._discard()
            msg = f"cannot open cache {path}: {exc}"
            raise StoreError(msg) from exc

    def get(self, key: str) -> bytes | None:
        """Return the stored value or None.

        Raises:
            StoreError: The cache is closed or unreadable.
        """
        db = self._open_db()
        _check_key(key)
        if db is None:
            return None
        try:
            with self._lock:
                row = db.execute(
                    "SELECT value FROM kv WHERE key = ? AND typeof(value) = 'blob'"
                    " AND length(value) <= ?",
                    (key, MAX_VALUE_BYTES),
                ).fetchone()
        except (sqlite3.Error, UnicodeError, TypeError, OverflowError) as exc:
            msg = f"cache read failed: {exc}"
            raise StoreError(msg) from exc
        if row is None:
            return None
        value = row[0]
        if not isinstance(value, bytes):
            msg = "cache row is not a blob"
            raise StoreError(msg)
        return value

    def set(self, key: str, value: bytes) -> None:
        """Store ``value`` under ``key`` (last write wins).

        Raises:
            StoreError: The cache is read-only or closed, or the write failed.
        """
        db = self._open_db()
        _check_key(key)
        if self._read_only or db is None:
            msg = "cache is read-only"
            raise StoreError(msg)
        untyped: object = value  # callers can be untyped: check at runtime
        if not isinstance(untyped, bytes):
            msg = f"cache values must be bytes, not {type(untyped).__name__}"
            raise StoreError(msg)
        if len(value) > MAX_VALUE_BYTES:
            msg = f"cache value of {len(value)} bytes is larger than the {MAX_VALUE_BYTES} limit"
            raise StoreError(msg)
        try:
            with self._lock, db:
                db.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, value))
        except (sqlite3.Error, UnicodeError, TypeError, OverflowError) as exc:
            msg = f"cache write failed: {exc}"
            raise StoreError(msg) from exc

    def close(self) -> None:
        """Close the cache; calling it twice is fine."""
        with self._lock:
            self._discard()
            self._closed = True

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def _discard(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None

    def _open_db(self) -> sqlite3.Connection | None:
        if self._closed:
            msg = "cache is closed"
            raise StoreError(msg)
        return self._db


def _check_key(key: object) -> None:
    if not isinstance(key, str):
        msg = f"cache keys must be str, not {type(key).__name__}"
        raise StoreError(msg)
    if len(key) > MAX_KEY_CHARS:
        msg = f"cache key of {len(key)} characters is longer than the {MAX_KEY_CHARS} limit"
        raise StoreError(msg)


class LayeredKVCache:
    """Reads the ``overlay`` first, then the ``base``; writes go to the ``overlay`` only.

    PR jobs use main's shared cache as a read-only ``base`` and a per-job directory as the
    ``overlay``, so a PR can never poison the shared cache (ADR-0006).

    Args:
        base: The shared cache; never written through this object.
        overlay: The writable per-job cache.
    """

    def __init__(self, base: KVCache, overlay: KVCache) -> None:
        self._base = base
        self._overlay = overlay

    def get(self, key: str) -> bytes | None:
        """Return the overlay value, else the base value, else None.

        Raises:
            StoreError: A layer is closed or unreadable.
        """
        hit = self._overlay.get(key)
        return hit if hit is not None else self._base.get(key)

    def set(self, key: str, value: bytes) -> None:
        """Store ``value`` in the overlay (the base stays byte for byte unchanged).

        Raises:
            StoreError: The overlay is closed or the write failed.
        """
        self._overlay.set(key, value)

    def close(self) -> None:
        """Close both layers that can be closed; calling it twice is fine."""
        for layer in (self._overlay, self._base):
            closer = getattr(layer, "close", None)
            if callable(closer):
                closer()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def build_cache(
    mode: str,
    shared_dir: Path,
    overlay_dir: Path,
    namespace: Literal["target", "llm"] = "target",
) -> DiskKVCache | LayeredKVCache:
    """Open the cache of a job for its trust domain.

    ``shared`` returns the writable shared cache (main and nightly jobs). ``overlay`` returns
    ``LayeredKVCache(read-only shared, writable overlay)`` (PR jobs); a shared cache that does not
    exist yet is an empty base and is not created.

    Args:
        mode: ``shared`` or ``overlay``.
        shared_dir: Root of the shared cache.
        overlay_dir: Root of the per-job overlay (used in ``overlay`` mode only).
        namespace: ``target`` (runner) or ``llm`` (``LLMClient``).

    Returns:
        A cache; close it (it is a context manager) when the job ends.

    Raises:
        StoreError: Unknown ``mode``, or a cache file cannot be opened.
    """
    if mode == "shared":
        return DiskKVCache(shared_dir, namespace)
    if mode != "overlay":
        msg = f"unknown cache mode {mode!r}; use 'shared' or 'overlay'"
        raise StoreError(msg)
    base = DiskKVCache(shared_dir, namespace, read_only=True)
    try:
        return LayeredKVCache(base, DiskKVCache(overlay_dir, namespace))
    except StoreError:
        base.close()
        raise

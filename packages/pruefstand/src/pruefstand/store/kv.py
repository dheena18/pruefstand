"""``DiskKVCache``: the persistent byte cache behind the ``target`` and ``llm`` namespaces."""

import sqlite3
from pathlib import Path
from types import TracebackType
from typing import Literal, Self

import diskcache  # type: ignore[import-untyped]  # diskcache ships no stubs or py.typed marker

from pruefstand.core.errors import StoreError


class DiskKVCache:
    """A ``KVCache`` on ``diskcache.Cache(directory / namespace)`` (decision D75).

    Keys are opaque strings (callers pass ``stable_hash`` output); values are bytes. In
    ``read_only`` mode (PR jobs) ``get`` works and ``set`` raises; a missing directory is an
    empty cache and is not created.

    Args:
        directory: Cache root; each namespace lives in its own subdirectory.
        namespace: ``"target"`` (runner, target responses) or ``"llm"`` (``LLMClient``, T5.1).
        read_only: Refuse writes.

    Raises:
        StoreError: (constructor) the cache directory cannot be opened.
    """

    def __init__(
        self, directory: Path, namespace: Literal["target", "llm"], *, read_only: bool = False
    ) -> None:
        self._read_only = read_only
        self._closed = False
        path = directory / namespace
        self._cache: diskcache.Cache | None = None
        if read_only and not path.exists():
            return
        try:
            self._cache = diskcache.Cache(str(path))
        except (OSError, sqlite3.Error, diskcache.Timeout) as exc:
            msg = f"cannot open cache {path}: {exc}"
            raise StoreError(msg) from exc

    def get(self, key: str) -> bytes | None:
        """Return the stored value or None.

        Raises:
            StoreError: The cache is closed, unreadable, or holds a non-bytes value.
        """
        self._check_open()
        if self._cache is None:
            return None
        try:
            value = self._cache.get(key)
        except (OSError, sqlite3.Error, diskcache.Timeout) as exc:
            msg = f"cache read failed: {exc}"
            raise StoreError(msg) from exc
        if value is not None and not isinstance(value, bytes):
            msg = f"cache entry {key!r} is not bytes"
            raise StoreError(msg)
        return value

    def set(self, key: str, value: bytes) -> None:
        """Store ``value`` under ``key``.

        Raises:
            StoreError: The cache is read-only or closed, or the write failed.
        """
        self._check_open()
        if self._read_only or self._cache is None:
            msg = "cache is read-only"
            raise StoreError(msg)
        try:
            self._cache.set(key, value)
        except (OSError, sqlite3.Error, diskcache.Timeout) as exc:
            msg = f"cache write failed: {exc}"
            raise StoreError(msg) from exc

    def close(self) -> None:
        """Close the cache; calling it twice is fine."""
        if self._cache is not None:
            self._cache.close()
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

    def _check_open(self) -> None:
        if self._closed:
            msg = "cache is closed"
            raise StoreError(msg)

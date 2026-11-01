"""``DiskKVCache``: the persistent byte cache behind the ``target`` and ``llm`` namespaces.

Backed by one SQLite file per namespace (stdlib ``sqlite3``). Values are stored as opaque BLOBs
and returned as bytes; nothing is ever unpickled (D361).
"""

import sqlite3
import threading
from pathlib import Path
from types import TracebackType
from typing import Literal, Self

from pruefstand.core.errors import StoreError

_FILE = "cache.sqlite3"
_BUSY_TIMEOUT_S = 2.0


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
        StoreError: (constructor) the cache file cannot be opened or is not a database.
    """

    def __init__(
        self, directory: Path, namespace: Literal["target", "llm"], *, read_only: bool = False
    ) -> None:
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
        if db is None:
            return None
        try:
            with self._lock:
                row = db.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        except sqlite3.Error as exc:
            msg = f"cache read failed: {exc}"
            raise StoreError(msg) from exc
        return None if row is None else bytes(row[0])

    def set(self, key: str, value: bytes) -> None:
        """Store ``value`` under ``key`` (last write wins).

        Raises:
            StoreError: The cache is read-only or closed, or the write failed.
        """
        db = self._open_db()
        if self._read_only or db is None:
            msg = "cache is read-only"
            raise StoreError(msg)
        try:
            with self._lock, db:
                db.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, value))
        except sqlite3.Error as exc:
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

"""``CorpusMeta``: the served index is only used when it is complete and analysed like the app."""

import time
from collections.abc import Callable
from typing import Any

from rag_demo.analysis.fingerprint import check_fingerprint
from rag_demo.errors import IndexUnavailableError, RetrievalError
from rag_demo.retrieval.store import QdrantStore


class CorpusMeta:
    """Corpus version and tenants from the collection metadata, re-read every ``TTL_S`` seconds.

    Only a collection that is ``complete`` and whose analyzer fingerprint equals the app's is
    accepted; an unfinished, stale or differently analysed index is refused (the API answers 503),
    never served dense-only. The re-read follows an alias swap (``chunks_active``) to the new
    collection within ``TTL_S``.

    Args:
        store: The Qdrant client of the served collection or alias.
        expected: The app's own index fingerprint (``wiring.expected_fingerprint``).
        clock: Monotonic clock in seconds (tests).
    """

    TTL_S = 10.0

    def __init__(
        self,
        store: QdrantStore,
        expected: dict[str, Any],
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._store = store
        self._expected = expected
        self._clock = clock or (lambda: time.monotonic())  # noqa: PLW0108  (looked up per call)
        self._value: dict[str, Any] | None = None
        self._read_at = 0.0

    def get(self) -> dict[str, Any]:
        """The checked metadata (cached for ``TTL_S``).

        Raises:
            IndexUnavailableError: Metadata unreadable, incomplete build.
            IndexMismatchError: Another analyzer or hash scheme than the app's.
        """
        now = self._clock()
        if self._value is None or now - self._read_at >= self.TTL_S:
            self._value = self._read()
            self._read_at = now
        return self._value

    def _read(self) -> dict[str, Any]:
        try:
            meta = dict(self._store.metadata())
        except RetrievalError:
            msg = "index unavailable"
            raise IndexUnavailableError(msg) from None
        if not {"corpus_version", "tenants"} <= meta.keys():
            msg = "index unavailable"
            raise IndexUnavailableError(msg)
        if meta.get("complete") is not True:
            msg = "index build is not complete; re-index"
            raise IndexUnavailableError(msg)
        check_fingerprint(meta.get("analyzer"), self._expected)
        return meta

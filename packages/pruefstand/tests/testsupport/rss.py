"""Peak resident memory of this process during a block (``ru_maxrss`` is only a high-water mark)."""

import pathlib
import threading
import time
from types import TracebackType


def _rss_kib() -> int:
    with pathlib.Path("/proc/self/status").open(encoding="ascii") as handle:
        for line in handle:
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    return 0


class PeakRss:
    """Context manager: ``grown_kib`` is the highest sampled RSS minus the RSS at entry."""

    def __init__(self) -> None:
        self.grown_kib = 0
        self._stop = threading.Event()
        self._base = 0
        self._peak = 0
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        while not self._stop.is_set():
            self._peak = max(self._peak, _rss_kib())
            time.sleep(0.005)

    def __enter__(self) -> "PeakRss":
        self._base = self._peak = _rss_kib()
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._stop.set()
        self._thread.join()
        self._peak = max(self._peak, _rss_kib())
        self.grown_kib = self._peak - self._base

"""Machine-independent timing checks for unit tests (D840).

Unit tests never assert on wall-clock time: on a shared VM or a CI runner it varies by an order of
magnitude with load. Three tools cover what such tests are after:

* ``assert_scales_linearly``: a cost-ratio check for "4x the input costs about 4x, not 16x". It
  measures CPU time of this process (``time.process_time``; other processes do not count), takes the
  minimum of several runs and alternates the small and the big input so slow drift cancels out.
  The limit sits between the linear and the quadratic ratio (``linear_ratio_limit``).
* ``cpu_budget``: "this hostile input is handled without blowing up". A generous CPU-time ceiling,
  at least 10x the CPU time measured on the dev VM; a hang or a super-linear blow-up still fails.
* Time-dependent production code (timeouts, deadlines) is tested with an injected clock or with a
  blocking event instead of a sleep, never with a stopwatch.
"""

import gc
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

HANG_GUARD_S = 120.0  # a cost this high is a hang whatever the ratio says


def cpu_seconds(fn: Callable[[], object], *, collect: bool = True) -> float:
    """Run ``fn`` once and return the CPU seconds this process used.

    Args:
        fn: The call to measure.
        collect: Run a full garbage collection first. On a big test process that costs 0.1 s or
            more, so a caller that measures many runs collects once and passes ``False``.

    Returns:
        ``time.process_time`` delta; it does not grow when other processes compete for the CPU.
        The cyclic garbage collector is off during the call.
    """
    if collect:
        gc.collect()
    collecting = gc.isenabled()
    gc.disable()  # a full collection grows with the heap: not the algorithm under test
    try:
        start = time.process_time()
        fn()
        return time.process_time() - start
    finally:
        if collecting:
            gc.enable()


def linear_ratio_limit(scale: float) -> float:
    """The cost ratio a ``scale``-times larger input may reach.

    Linear code gives ``scale``, quadratic code ``scale ** 2``; the limit ``1.25 * scale ** 1.5``
    leaves a clear margin on both sides.

    Args:
        scale: Input size factor, > 1.

    Returns:
        The ratio limit.

    Examples:
        >>> linear_ratio_limit(4)
        10.0
        >>> round(linear_ratio_limit(8), 1)
        28.3
    """
    return float(1.25 * scale**1.5)


def assert_scales_linearly(
    small: Callable[[], object],
    big: Callable[[], object],
    *,
    scale: float,
    limit: float | None = None,
    reps: int = 5,
    floor_s: float = 1e-3,
) -> None:
    """Assert that ``big`` (``scale`` times the input of ``small``) costs about ``scale`` x more.

    Args:
        small: Runs the code on the small input (do the set-up outside, only the measured call in).
        big: Runs the code on the input ``scale`` times larger.
        scale: Size factor between the two inputs.
        limit: Largest allowed cost ratio (default ``linear_ratio_limit(scale)``).
        reps: Runs per input; the minimum counts, small and big alternate.
        floor_s: CPU seconds below which the small cost is treated as noise.

    Raises:
        AssertionError: The ratio exceeds the limit or the big input costs more than
            ``HANG_GUARD_S`` CPU seconds.
    """
    allowed = linear_ratio_limit(scale) if limit is None else limit
    best_small = best_big = float("inf")
    gc.collect()  # once: a full collection per run would dominate the test time
    for _ in range(reps):
        best_small = min(best_small, cpu_seconds(small, collect=False))
        best_big = min(best_big, cpu_seconds(big, collect=False))
    assert best_big < HANG_GUARD_S, f"{best_big:.1f} CPU s"
    ratio = best_big / max(best_small, floor_s)
    assert ratio <= allowed, f"{scale:g}x input cost {ratio:.1f}x (limit {allowed:.1f}x)"


@contextmanager
def cpu_budget(limit_s: float) -> Iterator[None]:
    """Assert that the block uses less than ``limit_s`` CPU seconds of this process.

    Pick the limit at least 10x the CPU time measured on the dev VM, so that load cannot trip it
    and a hang or blow-up still does.

    Args:
        limit_s: The CPU-time ceiling in seconds.

    Raises:
        AssertionError: After the block, when it used more CPU time than ``limit_s``.
    """
    start = time.process_time()
    yield
    used = time.process_time() - start
    assert used < limit_s, f"used {used:.2f} CPU s (limit {limit_s:g} s)"

"""RQ1 run plan (T7.3 S2, pure part): rq1 cases, correctness subsample, request kinds, night window.

Retrieval metrics need no generation: every ``rq1`` case goes to the target's ``/v1/retrieve``;
only the pre-registered, seeded correctness subsample of bases (and their perturbations) goes to
``/v1/query`` (round 13 P3.2, AI13-13). Grid runs are never dispatched in the night window
22:00-06:00 Europe/Berlin (D223).
"""

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

import numpy as np

from pruefstand.core.enums import Split
from pruefstand.core.errors import ConfigError
from pruefstand.core.models.testcase import TestCase

BERLIN = ZoneInfo("Europe/Berlin")
SEED = 1234


def rq1_cases(cases: Iterable[TestCase]) -> list[TestCase]:
    """Return the ``rq1`` cases only (RQ1 has its own split and never reads ``full``, P3.2)."""
    return [case for case in cases if case.split is Split.RQ1]


def correctness_subsample(bases: Sequence[str], size: int, seed: int = SEED) -> list[str]:
    """Draw the pre-registered correctness subsample of base ids (sorted, without replacement).

    Raises:
        ConfigError: ``size`` is negative or larger than the number of distinct bases.

    Examples:
        >>> a = correctness_subsample(["b3", "b1", "b2", "b1"], 2)
        >>> a == correctness_subsample(["b1", "b2", "b3"], 2)
        True
    """
    pool = sorted(set(bases))
    if not 0 <= size <= len(pool):
        msg = f"subsample size {size} not in [0, {len(pool)}]"
        raise ConfigError(msg)
    rng = np.random.default_rng(seed)
    return sorted(str(pool[i]) for i in rng.choice(len(pool), size=size, replace=False))


def request_plan(
    cases: Iterable[TestCase], subsample: Iterable[str]
) -> dict[str, Literal["query", "retrieve"]]:
    """Map every case id to ``query`` (base in the subsample) or ``retrieve`` (all other cases)."""
    chosen = set(subsample)
    return {case.id: "query" if case.base_id in chosen else "retrieve" for case in cases}


def check_dispatch_time(now: datetime) -> None:
    """Refuse a grid dispatch in the night window 22:00-06:00 Europe/Berlin (D223).

    Raises:
        ConfigError: ``now`` is naive or falls in the night window.
    """
    if now.tzinfo is None:
        msg = "dispatch time must be timezone-aware"
        raise ConfigError(msg)
    hour = now.astimezone(BERLIN).hour
    if hour >= 22 or hour < 6:
        msg = f"no grid dispatch in the night window (22:00-06:00 Europe/Berlin), got {hour:02d}h"
        raise ConfigError(msg)

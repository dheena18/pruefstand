"""Which cases a run executes: splits, block, stratum and judged subset (R12 N1.2, R13 P4.3).

Pure functions apart from ``resolve_block``, which reads the nightly counter file.
"""

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from pruefstand.core.enums import Split
from pruefstand.core.errors import ConfigError
from pruefstand.core.logging import get_logger
from pruefstand.core.models.testcase import TestCase
from pruefstand.pipeline._files import read_regular

Stratum = Literal["all", "refusal", "blocks"]
Tier = Literal["pr", "nightly", "bench"]
BLOCKS = (0, 1, 2)
_COUNTER_BYTES = 64
_COUNTER_DIGITS = 18

_log = get_logger(__name__)


def validate_selection(
    splits: Sequence[Split],
    *,
    tier: Tier,
    block: int | None,
    judged_subset: bool,
    stratum: Stratum,
) -> None:
    """Check that the selection flags fit the selected splits.

    Args:
        splits: The splits the run loads.
        tier: ``pr``, ``nightly`` or ``bench``.
        block: Resolved nightly block or None.
        judged_subset: Whether the run limits generation and judging to the judged subset.
        stratum: Case selector inside ``full``.

    Raises:
        ConfigError: ``block`` or a non-default ``stratum`` without exactly the ``full`` split,
            ``block`` outside 0..2, ``stratum="refusal"`` with a block, ``judged_subset`` without
            ``core``, or ``rq1`` outside the ``bench`` tier.
    """
    chosen = set(splits)
    if Split.RQ1 in chosen and tier != "bench":
        msg = "split rq1 runs offline only: use --tier bench"
        raise ConfigError(msg)
    if block is not None and block not in BLOCKS:
        msg = f"block must be 0, 1 or 2, got {block}"
        raise ConfigError(msg)
    if (block is not None or stratum != "all") and chosen != {Split.FULL}:
        msg = "--block and --stratum need exactly the split full (--split full)"
        raise ConfigError(msg)
    if stratum == "refusal" and block is not None:
        msg = "--stratum refusal cannot be combined with --block (the refusal stratum has no block)"
        raise ConfigError(msg)
    if judged_subset and Split.CORE not in chosen:
        msg = "--judged-subset needs the split core"
        raise ConfigError(msg)


def select_cases(
    cases: Sequence[TestCase], *, block: int | None, stratum: Stratum
) -> list[TestCase]:
    """Keep the cases of the chosen stratum and block (they apply to ``full`` only).

    ``refusal`` keeps cases without a block; ``blocks`` keeps cases with block ``block`` (any
    block when None); ``all`` keeps the refusal stratum plus those block cases, or every case when
    no block is given.

    Args:
        cases: The loaded cases (``validate_selection`` has accepted the flags).
        block: Resolved nightly block or None.
        stratum: Case selector.

    Returns:
        The selected cases in input order.

    Raises:
        ConfigError: The selection is empty.
    """
    if stratum == "refusal":
        chosen = [c for c in cases if c.block is None]
    elif stratum == "blocks":
        chosen = [c for c in cases if c.block is not None and block in (None, c.block)]
    elif block is None:
        chosen = list(cases)
    else:
        chosen = [c for c in cases if c.block in (None, block)]
    if not chosen:
        msg = f"the selection (block={block}, stratum={stratum}) matches no case"
        raise ConfigError(msg)
    return chosen


def _counter_path(env: Mapping[str, str]) -> Path:
    named = env.get("PRUEFSTAND_NIGHTLY_COUNTER")
    if named:
        return Path(named)
    home = env.get("PRUEFSTAND_HOME") or "~/pruefstand"
    return Path(home).expanduser() / "state" / "nightly_counter"


def _read_counter(path: Path) -> int:
    try:
        raw = read_regular(path, _COUNTER_BYTES)
    except FileNotFoundError:
        return 0
    except OSError as exc:
        msg = f"nightly counter {path}: cannot read: {exc.strerror or 'not a regular file'}"
        raise ConfigError(msg) from exc
    text = raw.decode("ascii", errors="replace").strip()
    if not text.isascii() or not text.isdigit() or len(text) > _COUNTER_DIGITS:
        msg = f"nightly counter {path}: not a non-negative integer"
        raise ConfigError(msg)
    return int(text)


def resolve_block(spec: str | None, env: Mapping[str, str] | None = None) -> int | None:
    """Turn the ``--block`` argument into a block number (``auto`` reads the nightly counter).

    ``auto`` is the integer in the file named by ``PRUEFSTAND_NIGHTLY_COUNTER`` (unset:
    ``$PRUEFSTAND_HOME/state/nightly_counter``) modulo 3; a missing file means block 0; the clock
    plays no part (R13 P4.4).

    Args:
        spec: None, ``"auto"``, ``"0"``, ``"1"`` or ``"2"``.
        env: Environment, default ``os.environ``.

    Returns:
        The block, or None when ``spec`` is None.

    Raises:
        ConfigError: ``spec`` is something else, or the counter file is unparsable.

    Examples:
        >>> resolve_block("2")
        2
        >>> resolve_block(None) is None
        True
    """
    if spec is None:
        return None
    if spec == "auto":
        path = _counter_path(os.environ if env is None else env)
        block = _read_counter(path) % len(BLOCKS)
        _log.info("nightly_block_resolved", block=block, counter_file=str(path))
        return block
    if spec in {"0", "1", "2"}:
        return int(spec)
    msg = f"--block must be auto, 0, 1 or 2, got {spec[:20]!r}"
    raise ConfigError(msg)

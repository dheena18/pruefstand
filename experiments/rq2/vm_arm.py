"""T5.4e skeleton: the RQ2 arms (b', c) on the VM CPU model instead of GitHub Models (D1242).

GitHub Models is retired (D1202). The large non-gemma arm (b') and the tier-1 arm (c) are measured
with the VM CPU model Ministral 3 14B (``scripts/models/vm_llm.sh``, PR #165) through the
``openai_compatible_local`` backend of PR #166. Plan, order of steps and what must be merged first:
``docs/planning/T5.4e-vm-judge-plan.md``. Until #165 and #166 are on ``main`` this module only
plans (``--dry-run``): which items, how many calls, how many launcher sessions. It never starts
the server and never calls a model.

    uv run python experiments/rq2/vm_arm.py --dry-run --size 300 --s-per-call 45
"""

import argparse
import importlib.util
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run as a script: import rq2.*

from rq2.binarise import is_local
from rq2.calib_schema import CalibrationItem
from rq2.rq2_config import REPO, RQ2Config, load_config, load_items, set_available
from rq2.subsample import stratified_subsample

from pruefstand.core.errors import ConfigError

VM_JUDGE = "openai_compatible_local/ministral-3-14b-instruct-2512"
"""The VM model pin of PR #166 (``datagen_pins.VM_DATAGEN_MODEL``); family ``mistral``."""
VM_FAMILY = "mistral"
SESSION_S = 100 * 60
"""Hard stop of one ``vm_llm.sh`` server session (PR #165)."""
SESSION_USE = 0.9
"""Share of a session planned for calls (start-up, model load and the tail stay free)."""
NEEDS = ("pruefstand.dataset.vm_datagen",)
"""Modules of PR #166 the real run needs (``check_vm_served``, ``build_vm_backend``)."""


def vm_items(cfg: RQ2Config, size: int) -> list[tuple[str, CalibrationItem]]:
    """The seeded per-set subsample of the publishable ``test`` sets for the VM judge.

    MEMERAG (``local_only``) is included: the VM model counts as local (``rq2.binarise``, plan
    step 3, D1283), so the text never leaves the VM; pending sets (``legal_hard``) are skipped.

    Args:
        cfg: The RQ2 configuration (seed, sets).
        size: Items per set (``stratified_subsample``, by label and hard type).

    Returns:
        ``(set name, item)`` pairs in set order.
    """
    out: list[tuple[str, CalibrationItem]] = []
    for entry in cfg.sets:
        if (entry.local_only and not is_local(VM_JUDGE)) or not set_available(entry):
            continue
        items = stratified_subsample(load_items(entry, "test"), size, cfg.seed)
        out += [(entry.name, item) for item in items]
    return out


def cassette_items(cfg: RQ2Config, n: int = 3) -> list[CalibrationItem]:
    """The first ``n`` VM-plan items of the publishable sets: what the VM judge cassettes hold.

    MEMERAG (CC BY-NC) is never in a committed cassette, so its set is skipped here.
    """
    return [item for name, item in vm_items(cfg, 300) if not cfg.set_named(name).local_only][:n]


def sessions(
    n_calls: int, s_per_call: float, session_s: float = SESSION_S, use: float = SESSION_USE
) -> list[range]:
    """Split ``n_calls`` sequential calls into batches that fit one launcher session each.

    Raises:
        ValueError: ``s_per_call`` is not positive or one call does not fit a session.

    Examples:
        >>> [len(r) for r in sessions(600, 45.0)]
        [120, 120, 120, 120, 120]
    """
    if s_per_call <= 0:
        msg = f"s_per_call must be positive (got {s_per_call})"
        raise ValueError(msg)
    per_session = math.floor(session_s * use / s_per_call)
    if per_session < 1:
        msg = f"one call ({s_per_call} s) does not fit a session of {session_s * use:.0f} s"
        raise ValueError(msg)
    return [range(k, min(k + per_session, n_calls)) for k in range(0, n_calls, per_session)]


def preflight() -> None:
    """Refuse the real run until PR #165 and PR #166 are merged.

    Raises:
        ConfigError: A module of PR #166 or ``scripts/models/vm_llm.sh`` (PR #165) is missing.
    """
    missing = [m for m in NEEDS if importlib.util.find_spec(m) is None]
    if not (REPO / "scripts/models/vm_llm.sh").is_file():
        missing.append("scripts/models/vm_llm.sh")
    if missing:
        msg = f"T5.4e needs PR #165 and PR #166 merged first (missing: {', '.join(missing)})"
        raise ConfigError(msg)


def main(argv: list[str] | None = None) -> int:
    """Print the plan (``--dry-run``); the real run is refused until the pilot step exists."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=300, help="items per publishable set")
    parser.add_argument("--s-per-call", type=float, default=45.0, help="measured in the pilot")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    cfg = load_config(REPO / "experiments/rq2/configs/rq2_judges.yaml")
    items = vm_items(cfg, args.size)
    plan = sessions(len(items), args.s_per_call)
    sys.stdout.write(
        f"{VM_JUDGE}: {len(items)} items, {len(plan)} sessions of <= {len(plan[0]) if plan else 0}"
        f" calls at {args.s_per_call:.0f} s/call\n"
    )
    if args.dry_run:
        return 0
    try:
        preflight()
    except ConfigError as err:
        sys.stderr.write(f"{err}\n")
        return 2
    sys.stderr.write("real run not implemented yet: plan step 2 (D1242)\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

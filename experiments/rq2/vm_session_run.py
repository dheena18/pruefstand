"""Run one resumable VM judge session of the T5.4e full run (guards: ``vm_sessions.py``).

    uv run python experiments/rq2/vm_session_run.py [--pairs] [--sets ...] [--limit N] [--dry-run]

Exit 0: ``done`` (every call cached, final parquets written) or ``stopped: <reason>`` (run it
again later); 75: refused to start (night window, stop file, ``vm_llm.sh`` busy); 1: an error.
"""

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run as a script: import rq2.*

from rq2.make_degraded import load_pairs
from rq2.rq2_config import REPO, load_config
from rq2.run_judges import make_judge, select_items
from rq2.vm_arm import VM_JUDGE
from rq2.vm_sessions import ancestors, current_stop, deadline, server_pid, start_refusal

from pruefstand.core.errors import PruefstandError
from pruefstand.core.models.judge import JudgeTask
from pruefstand.judges.judge import Judge
from pruefstand.judges.output import make_task
from pruefstand.llm.recorder import CallRecorder

VM_LLM = REPO / "scripts/models/vm_llm.sh"
CONFIG = REPO / "experiments/rq2/configs/rq2_judges.yaml"
LOG = REPO / "data/derived/rq2/vm_sessions.jsonl"
PROGRESS_EVERY = 10


def state_dir() -> Path:
    """``vm_llm.sh``'s state directory (same default as the script)."""
    if named := os.environ.get("VM_LLM_STATE_DIR"):
        return Path(named)
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local/state")
    return Path(base) / "pruefstand-vm-llm"


def _inputs(value: object) -> dict[str, str]:
    """A pair side's judge inputs (a JSON object of strings)."""
    if not isinstance(value, dict):
        msg = f"pair inputs must be an object, got {type(value).__name__}"
        raise TypeError(msg)
    return {str(k): str(v) for k, v in value.items()}


def planned_tasks(args: argparse.Namespace) -> list[JudgeTask]:
    """Every judge call of the arm in ``run_judges`` order: items, then both sides of each pair."""
    cfg = load_config(CONFIG)
    entry = next(j for j in cfg.judges if j.id == VM_JUDGE)
    sets = [cfg.set_named(n) for n in args.sets] if args.sets else list(cfg.sets)
    tasks = [
        make_task(i.metric, **i.inputs)
        for _, i in select_items(cfg, entry, sets, "test", args.limit)
    ]
    for pair in load_pairs() if args.pairs else []:
        metric = str(pair["metric"])
        tasks += [make_task(metric, **_inputs(pair[side])) for side in ("inputs", "degraded")]
    return tasks


async def score_until_stopped(
    judge: Judge, tasks: list[JudgeTask], holders: list[int]
) -> str | None:
    """Score ``tasks`` in order; return the stop reason, or None when all are scored."""
    until = deadline(datetime.now(UTC))
    recorder_start = datetime.now(UTC)
    for n, task in enumerate(tasks, 1):
        reason = current_stop(until, holders)
        if reason is not None:
            return reason
        try:
            await judge.score(task)
        except PruefstandError as err:
            sys.stdout.write(f"call {n}: {type(err).__name__}\n")
        if n % PROGRESS_EVERY == 0:
            spent = (datetime.now(UTC) - recorder_start).total_seconds()
            sys.stdout.write(f"{n}/{len(tasks)} calls, {spent / n:.1f} s/call this session\n")
    return None


def _log(row: dict[str, object]) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")


def run_session(args: argparse.Namespace) -> int:
    """Start the server, score until done or stopped, always stop the server."""
    if refusal := start_refusal(datetime.now(UTC)):
        sys.stdout.write(f"refused: {refusal}\n")
        return 75
    tasks = planned_tasks(args)
    started = subprocess.run([str(VM_LLM), "start", "14b"], check=False, timeout=900)  # noqa: S603
    if started.returncode != 0:
        sys.stdout.write(f"refused: vm_llm.sh start exit {started.returncode}\n")
        return 75 if started.returncode == 75 else 1
    row: dict[str, object] = {"start": datetime.now(UTC).isoformat(), "planned": len(tasks)}
    try:
        pid = server_pid(state_dir())
        holders = ancestors(pid) if pid is not None else []
        recorder = CallRecorder()
        cfg = load_config(CONFIG)
        judge = make_judge(
            next(j for j in cfg.judges if j.id == VM_JUDGE), REPO / cfg.cache_dir, recorder
        )
        reason = asyncio.run(score_until_stopped(judge, tasks, holders))
        row["new_calls"] = len(recorder.rows)
        if reason is None:
            final = [
                sys.executable,
                str(REPO / "experiments/rq2/run_judges.py"),
                "--judge",
                VM_JUDGE,
            ]
            final += (["--sets", *args.sets] if args.sets else []) + (
                ["--pairs"] if args.pairs else []
            )
            final += ["--limit", str(args.limit)] if args.limit is not None else []
            subprocess.run(final, check=True, timeout=3600)  # noqa: S603  (all cache hits)
        row["result"] = "done" if reason is None else f"stopped: {reason}"
    finally:
        subprocess.run([str(VM_LLM), "stop"], check=False, timeout=300)  # noqa: S603
        row["stop"] = datetime.now(UTC).isoformat()
        _log(row)
    sys.stdout.write(f"{row['result']}\n")
    return 0


def _terminate(signum: int, _frame: object) -> None:
    raise SystemExit(128 + signum)  # unwinds through run_session's finally: the server stops


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--sets", nargs="*", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--pairs", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="print the planned calls and stop")
    args = parser.parse_args(argv)
    if args.dry_run:
        sys.stdout.write(f"{VM_JUDGE}: {len(planned_tasks(args))} planned calls\n")
        return 0
    signal.signal(signal.SIGTERM, _terminate)
    return run_session(args)


if __name__ == "__main__":
    raise SystemExit(main())

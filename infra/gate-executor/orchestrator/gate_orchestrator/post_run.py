"""Post-run health probe classification (D226, D1082, D1083; T6.2a S7).

After ``pruefstand run`` the orchestrator probes the infrastructure again (``health.sh`` without
``--repair``, plus the tunnel unit; no restart). The outcome decides between the run's own result
and an infra error (``"<kind>: <detail>"``, D245) that ``run_with_retry`` reports as ``error``:

* tunnel unit inactive → ``tunnel_lost``; exit 11 (endpoint or mode model not answering) and 12
  (``status.sh`` unreachable) → ``ollama_down``; 13 (resident digest changed) and 15 (not fully on
  the GPU) → ``model_reload``; 16 → ``data_root_unavailable``. Limit: with the tunnel unit active,
  an exit 11 is always ``ollama_down`` (the probe cannot tell a dead forward from a dead server).
* exit 10 (free VRAM below the minimum, e.g. another cluster user) and 14 (cluster bin dir differs
  from the checkout) do not touch a finished run: logged as WARN, the run's result stands, unless a
  ``resident:`` digest-differs or ``placement:`` FAIL row is also present (``health.sh`` exits with
  the first code of 16 11 12 14 13 15 10, so 14 hides 13/15): then ``model_reload``.
* any other exit (1, 2, 64: the script itself failed) → ``executor``.

Every probe command carries a subprocess timeout (``POST_RUN_TIMEOUT_S``) and runs in its own
process group, killed as a whole on timeout; a timeout raises
``subprocess.TimeoutExpired``, which ``run_with_retry`` treats as an infra error of kind
``executor``. ``evaluate`` (not built yet) calls :func:`post_run_infra_error` right after the run.
"""

import logging
import os
import signal
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from gate_orchestrator.lock import LOCK_HELD_ENV
from gate_orchestrator.preflight import DATA_ROOT_EXIT, IS_ACTIVE, Mode, fail_row

TimedRunner = Callable[[Sequence[str], Mapping[str, str], float], tuple[int, str]]
POST_RUN_TIMEOUT_S = 120.0
TERM_GRACE_S = 2.0
DRAIN_S = 5.0
KIND_FOR_EXIT = {
    11: "ollama_down",
    12: "ollama_down",
    13: "model_reload",
    15: "model_reload",
    DATA_ROOT_EXIT: "data_root_unavailable",
}
WARN_ONLY_EXITS = frozenset({10, 14})
LOG = logging.getLogger("gate_orchestrator.post_run")


def subprocess_runner(
    argv: Sequence[str], env: Mapping[str, str], timeout_s: float
) -> tuple[int, str]:
    """Run ``argv`` in its own process group with a timeout; return ``(exit code, stdout)``.

    On timeout the whole group gets SIGTERM, then after a 2 s grace SIGKILL (``killpg``: ``bash``
    and its children such as ``ssh``, ``curl``, ``gpu_health.py``), never anything outside it;
    all waits after the timeout are bounded (``_stop_group``).

    Raises:
        subprocess.TimeoutExpired: the command ran longer than ``timeout_s``.
    """
    proc = subprocess.Popen(  # noqa: S603 - fixed argv from this module, never from a PR
        list(argv), env=dict(env), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        start_new_session=True,
    )  # fmt: skip
    try:
        out, _ = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _stop_group(proc)
        raise
    return proc.returncode, out


def _stop_group(proc: "subprocess.Popen[str]") -> None:
    """Stop the probe's own process group: TERM, a 2 s grace, then KILL; all waits bounded.

    TERM first lets ``health.sh``'s EXIT trap remove its temp dir (D1083). A process that left the
    group and still holds the pipe cannot block: after ``DRAIN_S`` the pipe is closed.
    """
    for sig, wait_s in ((signal.SIGTERM, TERM_GRACE_S), (signal.SIGKILL, DRAIN_S)):
        try:
            os.killpg(proc.pid, sig)  # its own session: pgid == pid, nothing outside it
        except ProcessLookupError:
            break
        try:
            proc.communicate(timeout=wait_s)
        except subprocess.TimeoutExpired:
            continue
        return
    if proc.stdout is not None:
        proc.stdout.close()  # a daemon outside the group keeps the write end; stop reading
    proc.wait(timeout=DRAIN_S)


def _model_change_row(csv: str) -> str:
    """``"<check> <detail>"`` of a resident-digest or placement FAIL row, else ``""``."""
    for line in csv.splitlines():
        parts = line.split(",", 2)
        if len(parts) != 3 or parts[1] != "FAIL":
            continue
        digest = parts[0].startswith("resident:") and "differs from the catalogue" in parts[2]
        if digest or parts[0].startswith("placement:"):
            return f"{parts[0]} {parts[2]}"
    return ""


def post_run_infra_error(
    mode: Mode,
    health_sh: Path,
    run: TimedRunner,
    env: Mapping[str, str],
    *,
    timeout_s: float = POST_RUN_TIMEOUT_S,
) -> str | None:
    """Probe after the run; ``None`` when the run's result stands, else its ``infra_error``.

    Args:
        mode: the job's mode (``night`` for the nightly).
        health_sh: ``infra/gpu/health.sh`` of the trusted checkout.
        run: ``(argv, env, timeout_s) -> (exit code, stdout)``, e.g. :func:`subprocess_runner`.
        env: the locked job's child env (``PRUEFSTAND_LOCK_HELD=1``).
        timeout_s: per-command timeout.

    Returns:
        ``None`` or ``"<kind>: post-run ..."`` (kinds in the module docstring).

    Raises:
        ValueError: called without the GPU lock.
    """
    if env.get(LOCK_HELD_ENV) != "1":
        msg = "post-run probe needs PRUEFSTAND_LOCK_HELD=1 (run it under the GPU lock)"
        raise ValueError(msg)
    if run(IS_ACTIVE, env, timeout_s)[0] != 0:
        return "tunnel_lost: pruefstand-tunnel inactive after the run"
    code, out = run(("bash", str(health_sh), "--mode", mode), env, timeout_s)
    if code == 0:
        return None
    row = fail_row(out, code)
    detail = f"post-run health.sh exit {code}" + (f" ({row})" if row else "")
    if code in WARN_ONLY_EXITS:
        changed = _model_change_row(out)  # health.sh reports only the first code: 14 hides 13/15
        if changed:
            return f"model_reload: post-run health.sh exit {code} ({changed})"
        LOG.warning("post-run probe WARN, run result kept: %s", detail)
        return None
    return f"{KIND_FOR_EXIT.get(code, 'executor')}: {detail}"

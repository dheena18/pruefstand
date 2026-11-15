"""Post-run health probe classification (D226, D1082; T6.2a S7).

After ``pruefstand run`` the orchestrator probes the infrastructure again (``health.sh`` without
``--repair``, plus the tunnel unit; no restart). A failed probe means the run cannot be trusted as a
candidate result: it is an infra error (``"<kind>: <detail>"``, D245) that ``run_with_retry``
reports as ``error`` and retries once / asks for a re-dispatch, never a candidate ``failure``. A
passing probe keeps the run's own result (including timeouts, which stay candidate errors, D1082).
``evaluate`` (not built yet) calls :func:`post_run_infra_error` right after the run.
"""

from collections.abc import Mapping
from pathlib import Path

from gate_orchestrator.lock import LOCK_HELD_ENV
from gate_orchestrator.preflight import DATA_ROOT_EXIT, IS_ACTIVE, Mode, Runner, fail_row

KIND_FOR_EXIT = {13: "model_reload", 15: "model_reload", DATA_ROOT_EXIT: "data_root_unavailable"}


def post_run_infra_error(
    mode: Mode, health_sh: Path, run: Runner, env: Mapping[str, str]
) -> str | None:
    """Probe after the run; ``None`` when healthy, else the run's ``infra_error``.

    Args:
        mode: the job's mode (``night`` for the nightly).
        health_sh: ``infra/gpu/health.sh`` of the trusted checkout.
        run: ``(argv, env) -> (exit code, stdout)``.
        env: the locked job's child env (``PRUEFSTAND_LOCK_HELD=1``).

    Returns:
        ``None`` or ``"<kind>: post-run ..."`` with kind ``tunnel_lost``, ``ollama_down``,
        ``model_reload`` (digest or placement changed) or ``data_root_unavailable``.

    Raises:
        ValueError: called without the GPU lock.
    """
    if env.get(LOCK_HELD_ENV) != "1":
        msg = "post-run probe needs PRUEFSTAND_LOCK_HELD=1 (run it under the GPU lock)"
        raise ValueError(msg)
    if run(IS_ACTIVE, env)[0] != 0:
        return "tunnel_lost: pruefstand-tunnel inactive after the run"
    code, out = run(("bash", str(health_sh), "--mode", mode), env)
    if code == 0:
        return None
    row = fail_row(out, code)
    kind = KIND_FOR_EXIT.get(code, "ollama_down")
    detail = f"post-run health.sh exit {code}" + (f" ({row})" if row else "")
    return f"{kind}: {detail}"

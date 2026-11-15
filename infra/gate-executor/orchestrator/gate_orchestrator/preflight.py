"""Preflight under the GPU lock (D200, D208, D227, D228, ADR-0019): tunnel, ``health.sh --repair``.

Steps: ``systemctl is-active pruefstand-tunnel`` (system unit; if inactive one
``sudo -n systemctl restart pruefstand-tunnel``, the only sudoers line of ``pruefstand``) →
``health.sh --repair --mode <job mode>`` with ``PRUEFSTAND_LOCK_HELD=1``. Any failure is posted with
``post_status(sha, "error", "executor unhealthy: <reason>")`` (never ``set_check``) and nothing is
recorded in ``processed.jsonl``. The command runner is injected (tests never call systemd or ssh).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from gate_orchestrator.lock import LOCK_HELD_ENV
from gate_orchestrator.status import StatusPoster, unhealthy

Runner = Callable[[Sequence[str], Mapping[str, str]], tuple[int, str]]
Mode = Literal["day", "night"]
TUNNEL_UNIT = "pruefstand-tunnel"
IS_ACTIVE = ("systemctl", "is-active", "--quiet", TUNNEL_UNIT)
RESTART = ("sudo", "-n", "systemctl", "restart", TUNNEL_UNIT)
DATA_ROOT_EXIT = 16
REASONS = {
    10: "gpu memory",
    11: "ollama endpoint",
    12: "cluster status unreachable",
    13: "model digest mismatch",
    14: "cluster scripts out of date",
    15: "model not fully on the GPU",
    DATA_ROOT_EXIT: "data root unavailable",
}


@dataclass(frozen=True)
class Preflight:
    """Outcome: ``reason`` None = healthy; ``infra_error`` feeds the heartbeat ``last_result``."""

    reason: str | None = None
    infra_error: str | None = None

    @property
    def ok(self) -> bool:
        """True when every check passed."""
        return self.reason is None


# The FAIL row that explains each exit code (row formats of infra/gpu/health.sh + gpu_health.py,
# D1079): (check prefixes, text the detail must contain or "").
ROW_FOR_EXIT: dict[int, tuple[tuple[str, ...], str]] = {
    10: (("vram:",), ""),
    11: (("endpoint:", "resident:", "second-server"), ""),
    12: (("cluster-status",), ""),
    13: (("resident:",), "differs from the catalogue"),
    14: (("bin-dir",), ""),
    15: (("placement:",), ""),
    DATA_ROOT_EXIT: (("data-root",), ""),
}


def _fail_row(csv: str, code: int) -> str:
    """``"<check> <detail>"`` of the FAIL row matching ``code`` (else the first FAIL row)."""
    prefixes, needle = ROW_FOR_EXIT.get(code, ((), ""))
    fails = [
        p
        for p in (line.split(",", 2) for line in csv.splitlines())
        if len(p) == 3 and p[1] == "FAIL"
    ]
    matching = (
        [p for p in fails if p[0].startswith(prefixes) and needle in p[2]] if prefixes else []
    )
    chosen = matching or fails
    if not chosen:
        return ""
    check, _, detail = chosen[0]
    return f"{check} {detail}".strip()


def _health(mode: Mode, health_sh: Path, run: Runner, env: Mapping[str, str]) -> Preflight:
    code, out = run(("bash", str(health_sh), "--repair", "--mode", mode), env)
    if code == 0:
        return Preflight()
    detail = _fail_row(out, code) or f"health.sh exit {code}"
    reason = REASONS.get(code, f"health.sh exit {code}")
    if code == DATA_ROOT_EXIT:
        return Preflight(reason, f"data_root_unavailable: {detail}")
    if code == 13:
        return Preflight(f"{reason} ({detail})")
    return Preflight(reason)


def run_preflight(mode: Mode, health_sh: Path, run: Runner, env: Mapping[str, str]) -> Preflight:
    """Tunnel unit (one restart attempt), then ``health.sh --repair`` in the job's mode.

    Args:
        mode: ``night`` for the nightly, else ``day``.
        health_sh: path of ``infra/gpu/health.sh`` in the trusted checkout.
        run: ``(argv, env) -> (exit code, stdout)``.
        env: the locked job's child env; must carry ``PRUEFSTAND_LOCK_HELD=1``.

    Returns:
        :class:`Preflight`.

    Raises:
        ValueError: ``env`` lacks ``PRUEFSTAND_LOCK_HELD=1`` (preflight runs only under the lock).
    """
    if env.get(LOCK_HELD_ENV) != "1":
        msg = "preflight needs PRUEFSTAND_LOCK_HELD=1 (run it under the GPU lock)"
        raise ValueError(msg)
    if run(IS_ACTIVE, env)[0] != 0:
        run(RESTART, env)
        if run(IS_ACTIVE, env)[0] != 0:
            return Preflight("tunnel", "tunnel_lost: pruefstand-tunnel inactive after one restart")
    return _health(mode, health_sh, run, env)


def report_preflight(sha: str, result: Preflight, poster: StatusPoster) -> bool:
    """Post ``error`` "executor unhealthy: <reason>" for a failed preflight; return ``ok``."""
    if result.reason is not None:
        poster.post_status(sha, "error", unhealthy(result.reason))
    return result.ok

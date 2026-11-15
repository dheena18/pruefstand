"""D1082: the post-run health probe decides between a candidate result and an infra error.

Row formats are the real ones of ``infra/gpu/health.sh`` / ``gpu_health.py``.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from gate_orchestrator.post_run import post_run_infra_error

HEALTH = Path("infra/gpu/health.sh")
LOCKED = {"PRUEFSTAND_LOCK_HELD": "1"}


class Commands:
    def __init__(self, *, tunnel: int = 0, health: tuple[int, str] = (0, "")) -> None:
        self.tunnel, self.health = tunnel, health
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
        self.calls.append(tuple(argv))
        if argv[:2] == ("systemctl", "is-active"):
            return self.tunnel, ""
        return self.health


def test_healthy_after_the_run_keeps_the_candidate_result() -> None:
    cmds = Commands()
    assert post_run_infra_error("day", HEALTH, cmds, LOCKED) is None
    assert ("bash", str(HEALTH), "--mode", "day") in cmds.calls
    assert not any("--repair" in c for c in cmds.calls)  # a probe, never a repair, after the run
    assert not any(c[0] == "sudo" for c in cmds.calls)


@pytest.mark.parametrize(
    ("code", "check", "detail", "kind"),
    [
        (11, "endpoint:http://127.0.0.1:11434", "/api/tags does not answer", "ollama_down"),
        (12, "cluster-status", "status.sh did not answer over ssh (rc=255)", "ollama_down"),
        (
            13,
            "resident:gemma3:12b",
            "digest 0123456789ab differs from the catalogue",
            "model_reload",
        ),
        (
            15,
            "placement:gemma3:12b",
            "size_vram 100 < size 200: not fully on the GPU",
            "model_reload",
        ),
        (16, "data-root", "the data root does not exist", "data_root_unavailable"),
    ],
)
def test_failed_probe_is_an_infra_error(code: int, check: str, detail: str, kind: str) -> None:
    out = f"{check},FAIL,{detail}\n"
    got = post_run_infra_error("day", HEALTH, Commands(health=(code, out)), LOCKED)
    assert got == f"{kind}: post-run health.sh exit {code} ({check} {detail})"


def test_tunnel_down_after_the_run_is_tunnel_lost_without_a_restart() -> None:
    cmds = Commands(tunnel=3)
    assert post_run_infra_error("night", HEALTH, cmds, LOCKED) == (
        "tunnel_lost: pruefstand-tunnel inactive after the run"
    )
    assert not any(c[0] == "sudo" for c in cmds.calls)


def test_probe_needs_the_lock() -> None:
    with pytest.raises(ValueError, match="PRUEFSTAND_LOCK_HELD"):
        post_run_infra_error("day", HEALTH, Commands(), {})

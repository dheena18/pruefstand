"""D1082: the post-run health probe decides between a candidate result and an infra error.

Row formats are the real ones of ``infra/gpu/health.sh`` / ``gpu_health.py``.
"""

import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from gate_orchestrator.post_run import POST_RUN_TIMEOUT_S, post_run_infra_error, subprocess_runner

HEALTH = Path("infra/gpu/health.sh")
LOCKED = {"PRUEFSTAND_LOCK_HELD": "1"}


class Commands:
    def __init__(self, *, tunnel: int = 0, health: tuple[int, str] = (0, "")) -> None:
        self.tunnel, self.health = tunnel, health
        self.calls: list[tuple[str, ...]] = []
        self.timeouts: list[float] = []

    def __call__(
        self, argv: Sequence[str], env: Mapping[str, str], timeout_s: float
    ) -> tuple[int, str]:
        self.calls.append(tuple(argv))
        self.timeouts.append(timeout_s)
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


@pytest.mark.parametrize(
    ("code", "out"),
    [
        (10, "vram:1,FAIL,free_mib=512 min_free_mib=1024\n"),
        (14, "bin-dir,FAIL,cluster scripts differ from this checkout; run deploy-cluster-bin.sh\n"),
    ],
)
def test_vram_or_bin_dir_after_the_run_keeps_the_finished_result(
    code: int, out: str, caplog: pytest.LogCaptureFixture
) -> None:
    # D1083: another cluster user's VRAM or a stale bin dir does not invalidate a finished run
    assert post_run_infra_error("day", HEALTH, Commands(health=(code, out)), LOCKED) is None
    assert f"exit {code}" in caplog.text


@pytest.mark.parametrize("code", [1, 2, 64])
def test_script_level_exit_is_an_executor_infra_error(code: int) -> None:
    got = post_run_infra_error("day", HEALTH, Commands(health=(code, "")), LOCKED)
    assert got == f"executor: post-run health.sh exit {code}"


def test_every_probe_command_carries_a_timeout() -> None:
    cmds = Commands()
    post_run_infra_error("day", HEALTH, cmds, LOCKED, timeout_s=45)
    assert cmds.timeouts == [45, 45]
    assert POST_RUN_TIMEOUT_S == 120


def test_subprocess_runner_enforces_the_timeout() -> None:
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess_runner(("sleep", "5"), {}, 0.2)
    assert subprocess_runner(("sh", "-c", "echo row; exit 3"), {}, 5) == (3, "row\n")

"""Preflight under the lock and the infra-failure retry (D200, D208, D226, D274, N6.1, N6.4)."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

import pytest
from gate_orchestrator.infra import infra_from_deltas, proxy_deltas, run_with_retry
from gate_orchestrator.lock import lock_path, run_locked
from gate_orchestrator.preflight import Preflight, report_preflight, run_preflight
from gate_orchestrator.status import infra_summary
from orch_testkit import SpyPoster

SHA = "d" * 40
HEALTH = Path("infra/gpu/health.sh")
LOCKED = {"PRUEFSTAND_LOCK_HELD": "1"}


class Commands:
    """Scripted ``(argv, env) -> (code, out)`` runner that records every call."""

    def __init__(self, *, tunnel: Sequence[int] = (0,), health: tuple[int, str] = (0, "")) -> None:
        self.tunnel = list(tunnel)
        self.health = health
        self.calls: list[tuple[tuple[str, ...], dict[str, str]]] = []

    def __call__(self, argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
        self.calls.append((tuple(argv), dict(env)))
        if argv[:2] == ("systemctl", "is-active"):
            return self.tunnel.pop(0) if len(self.tunnel) > 1 else self.tunnel[0], ""
        if argv[0] == "bash":
            return self.health
        return 0, ""

    def argvs(self) -> list[tuple[str, ...]]:
        return [argv for argv, _ in self.calls]


def test_preflight_runs_after_the_lock_is_held(tmp_path: Path, poster: SpyPoster) -> None:
    cmds = Commands()
    events: list[str] = []

    def body(env: dict[str, str]) -> Preflight:
        events.append("locked")
        return run_preflight("day", HEALTH, cmds, env)

    assert (
        run_locked(SHA, body, poster=poster, env={}, timeout_s=5, lock_dir=tmp_path) == Preflight()
    )
    assert events == ["locked"]
    assert lock_path(tmp_path).exists()


def test_preflight_refuses_to_run_without_the_lock() -> None:
    with pytest.raises(ValueError, match="PRUEFSTAND_LOCK_HELD"):
        run_preflight("day", HEALTH, Commands(), {})


@pytest.mark.parametrize("mode", ["day", "night"])
def test_health_repair_in_the_jobs_mode_with_lock_held(mode: Literal["day", "night"]) -> None:
    cmds = Commands()
    assert run_preflight(mode, HEALTH, cmds, LOCKED).ok
    argv, env = cmds.calls[-1]
    assert argv == ("bash", str(HEALTH), "--repair", "--mode", mode)
    assert env["PRUEFSTAND_LOCK_HELD"] == "1"
    assert all("flock" not in " ".join(argv) for argv in cmds.argvs())


def test_inactive_tunnel_gets_one_system_restart_then_passes() -> None:
    cmds = Commands(tunnel=(3, 0))
    assert run_preflight("day", HEALTH, cmds, LOCKED).ok
    assert cmds.argvs()[:3] == [
        ("systemctl", "is-active", "--quiet", "pruefstand-tunnel"),
        ("sudo", "-n", "systemctl", "restart", "pruefstand-tunnel"),
        ("systemctl", "is-active", "--quiet", "pruefstand-tunnel"),
    ]
    assert all("--user" not in argv for argv in cmds.argvs())


def test_tunnel_still_inactive_is_unhealthy_tunnel(poster: SpyPoster) -> None:
    cmds = Commands(tunnel=(3,))
    result = run_preflight("day", HEALTH, cmds, LOCKED)
    assert result.reason == "tunnel"
    assert sum(argv[1] == "-n" for argv in cmds.argvs()) == 1
    assert not report_preflight(SHA, result, poster)
    assert poster.calls == [
        ("post_status", SHA, "error", "executor unhealthy: tunnel", "pruefstand/gate")
    ]


@pytest.mark.parametrize(
    ("code", "out", "description"),
    [
        (10, "vram:gpu0,FAIL,512 MiB free\n", "executor unhealthy: gpu memory"),
        (11, "", "executor unhealthy: ollama endpoint"),
        (
            13,
            "digest:gemma3:12b,FAIL,b92b != 0000\n",
            "executor unhealthy: model digest mismatch (digest:gemma3:12b b92b != 0000)",
        ),
        (
            16,
            "data_root,FAIL,/mnt/pruefstand not writable\n",
            "executor unhealthy: data root unavailable",
        ),
        (15, "", "executor unhealthy: model not fully on the GPU"),
        (99, "", "executor unhealthy: health.sh exit 99"),
    ],
)
def test_health_exit_codes_post_error_via_post_status(
    code: int, out: str, description: str, poster: SpyPoster
) -> None:
    result = run_preflight("day", HEALTH, Commands(health=(code, out)), LOCKED)
    assert not report_preflight(SHA, result, poster)
    assert poster.calls == [("post_status", SHA, "error", description, "pruefstand/gate")]


def test_data_root_failure_feeds_the_heartbeat_last_result() -> None:
    result = run_preflight(
        "day", HEALTH, Commands(health=(16, "data_root,FAIL,less than 20 GB free\n")), LOCKED
    )
    assert result.infra_error is not None
    assert result.infra_error.startswith("data_root_unavailable: ")
    assert "20 GB" in result.infra_error


def test_healthy_preflight_posts_nothing(poster: SpyPoster) -> None:
    assert report_preflight(SHA, run_preflight("day", HEALTH, Commands(), LOCKED), poster)
    assert poster.calls == []


def test_proxy_deltas_and_infra_kind() -> None:
    before = {"model_reloads": 2, "upstream_errors": 5, "requests": 100}
    after = {"model_reloads": 2, "upstream_errors": 8, "requests": 900}
    deltas = proxy_deltas(before, after)
    assert deltas == {"model_reloads": 0, "upstream_errors": 3}
    assert (infra_from_deltas(deltas) or "").startswith("proxy_upstream: ")
    assert (infra_from_deltas({"model_reloads": 1, "upstream_errors": 0}) or "").startswith(
        "model_reload: "
    )
    assert infra_from_deltas({"model_reloads": 0, "upstream_errors": 0}) is None


@pytest.mark.parametrize(
    "after", [{"model_reloads": 0, "upstream_errors": 9}, {"upstream_errors": 9}]
)
def test_proxy_restart_or_missing_counter_is_an_error(after: dict[str, int]) -> None:
    with pytest.raises(ValueError, match="model_reloads"):
        proxy_deltas({"model_reloads": 2, "upstream_errors": 5}, after)


class Job:
    def __init__(self, outcomes: Sequence[str | None]) -> None:
        self.outcomes = list(outcomes)
        self.events: list[str] = []
        self.recorded: list[str] = []

    def attempt(self, number: int) -> str | None:
        self.events.append(f"attempt {number}")
        return self.outcomes[number - 1]

    def repair(self) -> None:
        self.events.append("repair")


def _retry(job: Job, poster: SpyPoster) -> int:
    return run_with_retry(
        SHA, job.attempt, repair=job.repair, poster=poster, record_error=job.recorded.append
    )


def test_first_infra_failure_reports_repairs_and_retries_once(poster: SpyPoster) -> None:
    job = Job(["proxy_upstream: 3 upstream errors during the run", None])
    assert _retry(job, poster) == 2
    assert job.events == ["attempt 1", "repair", "attempt 2"]
    assert poster.calls == [
        (
            "set_check",
            SHA,
            "insufficient_data",
            "proxy_upstream: 3 upstream errors during the run; retrying once",
            "False",
            "True",
        )
    ]
    assert job.recorded == []


def test_second_infra_failure_asks_for_a_redispatch_and_is_recorded(poster: SpyPoster) -> None:
    job = Job(["tunnel_lost: ssh exited", "ollama_down: no answer"])
    assert _retry(job, poster) == 2
    assert job.events == ["attempt 1", "repair", "attempt 2"]
    assert [c[3] for c in poster.calls] == [
        "tunnel_lost: ssh exited; retrying once",
        "ollama_down: no answer; re-dispatch to retry",
    ]
    assert all(c[0] == "set_check" and c[5] == "True" for c in poster.calls)
    assert job.recorded == ["ollama_down: no answer; re-dispatch to retry"]


def test_no_infra_error_is_a_single_attempt(poster: SpyPoster) -> None:
    job = Job([None])
    assert _retry(job, poster) == 1
    assert poster.calls == []


def test_window_exceeded_is_never_retried(poster: SpyPoster) -> None:
    job = Job(["window_exceeded: nightly-gate", None])
    assert _retry(job, poster) == 1
    assert job.events == ["attempt 1"]
    assert poster.calls == []
    assert job.recorded == []


def test_infra_summary_has_exactly_two_attempts() -> None:
    assert infra_summary("model_reload: 1", 2) == "model_reload: 1; re-dispatch to retry"
    with pytest.raises(ValueError, match="attempt"):
        infra_summary("x", 3)


def test_no_other_infra_wording_in_the_package() -> None:
    pkg = Path(__file__).resolve().parents[1] / "gate_orchestrator"
    source = "\n".join(p.read_text(encoding="utf-8") for p in pkg.rglob("*.py"))
    assert "unhealthy during run" not in source
    assert "run-gate" not in source
    assert "not gated" not in source

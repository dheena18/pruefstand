"""Review of #170 (D1079): the right health.sh row per exit code, exceptions during the retry, the
lock released when the body raises, and MAINTENANCE checked again after the lock is taken.

The health rows below use the exact formats of ``infra/gpu/gpu_health.py`` / ``health.sh``.
"""

import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from gate_orchestrator.infra import InfraError, proxy_deltas, run_with_retry
from gate_orchestrator.lock import (
    LockTimeoutError,
    gpu_lock,
    lock_path,
    maintenance_path,
    run_locked,
)
from gate_orchestrator.preflight import run_preflight
from gate_orchestrator.status import MAINTENANCE
from orch_testkit import SpyPoster

from pruefstand.core.errors import TargetError

SHA = "d" * 40
LOCKED = {"PRUEFSTAND_LOCK_HELD": "1"}
EXIT13 = (
    "resident:qwen3.8:27b-q8_0,OK,digest 8f5fb6b71ea0\n"
    "placement:qwen3.8:27b-q8_0,FAIL,size_vram 100 < size 200: not fully on the GPU\n"
    "resident:gemma3:12b,FAIL,digest 0123456789ab differs from the catalogue\n"
    "placement:gemma3:12b,OK,gpu=1\n"
)


def _health(code: int, out: str) -> object:
    def run(argv: Sequence[str], _env: Mapping[str, str]) -> tuple[int, str]:
        return (code, out) if argv[0] == "bash" else (0, "")

    return run_preflight("day", Path("infra/gpu/health.sh"), run, LOCKED)


def test_digest_mismatch_names_the_resident_row_not_an_earlier_placement_row() -> None:
    result = _health(13, EXIT13)
    assert result.reason == (  # type: ignore[attr-defined]  # Preflight
        "model digest mismatch (resident:gemma3:12b digest 0123456789ab differs from the catalogue)"
    )


@pytest.mark.parametrize(
    ("code", "out", "infra_error"),
    [
        (
            16,
            "endpoint:http://127.0.0.1:11434,OK,answers\n"
            "data-root,FAIL,the data root is not writable by pruefstand\n",
            "data_root_unavailable: data-root the data root is not writable by pruefstand",
        ),
    ],
)
def test_data_root_uses_the_data_root_row(code: int, out: str, infra_error: str) -> None:
    assert _health(code, out).infra_error == infra_error  # type: ignore[attr-defined]


class Job:
    def __init__(
        self, first: object, second: object = None, repair: Exception | None = None
    ) -> None:
        self.outcomes, self.repair_exc = [first, second], repair
        self.recorded: list[str] = []

    def attempt(self, number: int) -> str | None:
        outcome = self.outcomes[number - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome  # type: ignore[return-value]

    def repair(self) -> None:
        if self.repair_exc is not None:
            raise self.repair_exc


def _retry(job: Job, poster: SpyPoster) -> int:
    return run_with_retry(
        SHA, job.attempt, repair=job.repair, poster=poster, record_error=job.recorded.append
    )


def test_repair_raising_is_the_second_infra_failure(poster: SpyPoster) -> None:
    job = Job("tunnel_lost: ssh exited", repair=subprocess.TimeoutExpired("health.sh", 300))
    assert _retry(job, poster) == 1
    assert [c[3] for c in poster.calls] == [
        "tunnel_lost: ssh exited; retrying once",
        "ollama_down: health.sh --repair failed (TimeoutExpired); re-dispatch to retry",
    ]
    assert len(job.recorded) == 1


@pytest.mark.parametrize("exc", [InfraError("ollama_down: no answer"), OSError("connection reset")])
def test_second_attempt_raising_infra_is_the_second_failure(
    poster: SpyPoster, exc: Exception
) -> None:
    job = Job("proxy_upstream: 3 upstream errors during the run", exc)
    assert _retry(job, poster) == 2
    assert poster.calls[-1][3].endswith("; re-dispatch to retry")
    assert poster.calls[-1][5] == "True"
    assert len(job.recorded) == 1


def test_first_attempt_raising_infra_retries(poster: SpyPoster) -> None:
    job = Job(InfraError("model_reload: 1 model reloads during the run"), None)
    assert _retry(job, poster) == 2
    assert [c[3] for c in poster.calls] == [
        "model_reload: 1 model reloads during the run; retrying once"
    ]
    assert job.recorded == []


@pytest.mark.parametrize(
    "exc", [TargetError("candidate broke", transient=False), ValueError("a bug")]
)
def test_candidate_or_bug_exceptions_are_not_infra(poster: SpyPoster, exc: Exception) -> None:
    with pytest.raises(type(exc)):
        _retry(Job(exc), poster)
    assert poster.calls == []


def test_proxy_restart_is_an_infra_error() -> None:
    with pytest.raises(InfraError, match="proxy_upstream"):
        proxy_deltas(
            {"model_reloads": 2, "upstream_errors": 5}, {"model_reloads": 0, "upstream_errors": 0}
        )


def test_lock_is_released_when_the_body_raises(tmp_path: Path, poster: SpyPoster) -> None:
    def body(_env: dict[str, str]) -> None:
        msg = "job failed"
        raise RuntimeError(msg)

    with pytest.raises(RuntimeError, match="job failed"):
        run_locked(SHA, body, poster=poster, env={}, timeout_s=5, lock_dir=tmp_path)
    with gpu_lock(lock_path(tmp_path), 0, sleep=lambda _s: None):
        pass  # obtained at once: the lock was released


def test_maintenance_is_checked_again_after_the_lock(tmp_path: Path, poster: SpyPoster) -> None:
    ran: list[dict[str, str]] = []
    path = lock_path(tmp_path)

    def sleep(_seconds: float) -> None:
        maintenance_path(tmp_path).write_text("", encoding="utf-8")  # appears while we wait
        holder.__exit__(None, None, None)

    holder = gpu_lock(path, 0)
    holder.__enter__()
    assert (
        run_locked(
            SHA, ran.append, poster=poster, env={}, timeout_s=60, lock_dir=tmp_path, sleep=sleep
        )
        is None
    )
    assert ran == []
    assert poster.calls == [("post_status", SHA, "pending", MAINTENANCE, "pruefstand/gate")]
    with gpu_lock(path, 0, sleep=lambda _s: None):
        pass
    assert LockTimeoutError is not None

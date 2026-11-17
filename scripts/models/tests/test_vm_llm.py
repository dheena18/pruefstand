"""vm_llm.sh: argument rules, the 127.0.0.1-only command, lock and check-slot refusals (D1200).

No server is started here (the ``live`` test in ``test_vm_llm_live.py`` does that); the lock tests
use the real ``infra/vm/pruefstand-lock`` against a temporary lock directory.
"""

import fcntl
import os
import socket
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "models" / "vm_llm.sh"
LOCK = REPO / "infra" / "vm" / "pruefstand-lock"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _env(tmp: Path, **extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("VM_LLM_", "PRUEFSTAND_"))}
    (tmp / "lock").mkdir(exist_ok=True)
    (tmp / "lock" / "gpu.lock").touch()
    env |= {
        "VM_LLM_STATE_DIR": str(tmp / "state"),
        "VM_LLM_MODELS_DIR": str(tmp / "models"),
        "VM_LLM_LOCK_CMD": str(LOCK),
        "VM_LLM_LOCK_WAIT_S": "0",
        "VM_LLM_READY_S": "20",
        "VM_LLM_START_WAIT_S": "1",
        "VM_LLM_PORT": str(_free_port()),
        "PRUEFSTAND_LOCK_DIR": str(tmp / "lock"),
        "PRUEFSTAND_CHECK_DIR": str(tmp / "check"),
    }
    return env | extra


def _run(tmp: Path, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
    cmd = ["bash", str(SCRIPT), *args]
    return subprocess.run(  # noqa: S603
        cmd, env=_env(tmp, **extra), capture_output=True, text=True, check=False, timeout=300
    )


@contextmanager
def _held(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield


def test_the_server_binds_127_0_0_1_pinned_niced_and_time_limited(tmp_path: Path) -> None:
    run = _run(tmp_path, "print-cmd")
    assert run.returncode == 0, run.stderr
    words = run.stdout.split("\n")
    assert words[words.index("--host") + 1] == "127.0.0.1"
    assert words[words.index("-t") + 1] == "16"
    assert words[words.index("taskset") + 2] == "0-19"
    assert words[words.index("nice") + 2] == "15"
    assert "-c3" in words
    assert "--no-slots" in words
    assert words[words.index("timeout") + 3] == "240m"
    assert words[words.index("-m") + 1].endswith("Ministral-3-14B-Instruct-2512-Q4_K_M.gguf")
    assert words[words.index("--alias") + 1] == "ministral-3-14b-instruct-2512"


def test_the_8b_model_and_its_file_name(tmp_path: Path) -> None:
    run = _run(tmp_path, "print-cmd", "8b")
    assert run.returncode == 0, run.stderr
    assert "Ministral-3-8B-Instruct-2512-Q4_K_M.gguf" in run.stdout
    assert "ministral-3-8b-instruct-2512" in run.stdout


def test_the_host_cannot_be_changed_by_the_environment(tmp_path: Path) -> None:
    run = _run(tmp_path, "print-cmd", VM_LLM_HOST="0.0.0.0")  # noqa: S104
    assert "0.0.0.0" not in run.stdout  # noqa: S104


@pytest.mark.parametrize("threads", ["81", "0", "160", "x"])
def test_more_than_80_threads_or_a_bad_number_is_refused(tmp_path: Path, threads: str) -> None:
    run = _run(tmp_path, "print-cmd", VM_LLM_THREADS=threads)
    assert run.returncode == 2
    assert "VM_LLM_THREADS" in run.stderr or "threads" in run.stderr


def test_80_threads_are_allowed(tmp_path: Path) -> None:
    assert _run(tmp_path, "print-cmd", VM_LLM_THREADS="80").returncode == 0


def test_an_unknown_model_or_cpu_list_is_refused(tmp_path: Path) -> None:
    assert _run(tmp_path, "print-cmd", "70b").returncode == 2
    assert _run(tmp_path, "print-cmd", VM_LLM_CPUS="0-19; rm -rf /").returncode == 2


def test_status_and_stop_when_nothing_runs(tmp_path: Path) -> None:
    assert _run(tmp_path, "status").returncode == 3
    stop = _run(tmp_path, "stop")
    assert stop.returncode == 0
    assert "not running" in stop.stdout


def test_start_is_refused_while_the_gate_holds_gpu_lock(tmp_path: Path) -> None:
    with _held(tmp_path / "lock" / "gpu.lock"):
        run = _run(tmp_path, "start")
    assert run.returncode == 75, run.stderr
    assert not (tmp_path / "state" / "pid").exists()


def test_start_is_refused_while_maintenance_is_set(tmp_path: Path) -> None:
    """D1285: a model swap is running; refused before the model file is even looked at."""
    (tmp_path / "lock").mkdir()
    (tmp_path / "lock" / "MAINTENANCE").touch()
    run = _run(tmp_path, "start")
    assert run.returncode == 75, run.stderr  # without the check: 2 (no model file here)
    assert "MAINTENANCE is set" in run.stderr
    assert not (tmp_path / "state" / "pid").exists()
    assert (tmp_path / "lock" / "MAINTENANCE").exists()  # never removed


def test_start_is_refused_while_a_check_slot_is_busy(tmp_path: Path) -> None:
    with _held(tmp_path / "check" / "slot2.lock"):
        run = _run(tmp_path, "start")
    assert run.returncode == 75, run.stderr
    assert "check slot 2" in run.stderr


def test_a_missing_model_file_fails_before_any_server_starts(tmp_path: Path) -> None:
    run = _run(tmp_path, "start")
    assert run.returncode == 2
    assert "model file missing" in run.stderr
    assert _run(tmp_path, "status").returncode == 3


def test_a_model_file_of_the_wrong_size_is_refused(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "Ministral-3-14B-Instruct-2512-Q4_K_M.gguf").write_bytes(b"GGUF")
    run = _run(tmp_path, "start")
    assert run.returncode == 2
    assert "wrong size" in run.stderr


@pytest.mark.slow  # hashes 5 GB (a sparse file): about 20-40 s
def test_a_file_of_the_right_size_but_another_hash_is_refused_and_not_cached(
    tmp_path: Path,
) -> None:
    models = tmp_path / "models"
    models.mkdir()
    with (models / "Ministral-3-8B-Instruct-2512-Q4_K_M.gguf").open("wb") as fh:
        fh.truncate(
            5198911904
        )  # sparse: the real size, zero bytes, so only the SHA-256 check can refuse it
    run = _run(tmp_path, "start", "8b", VM_LLM_READY_S="240")
    assert run.returncode == 2, run.stderr
    assert "SHA-256 mismatch" in run.stderr
    assert not (tmp_path / "state" / "verified-8b").exists()
    assert not (tmp_path / "state" / "pid").exists()


def test_the_inherited_lock_bypass_variable_is_ignored(tmp_path: Path) -> None:
    with _held(tmp_path / "lock" / "gpu.lock"):
        run = _run(tmp_path, "start", PRUEFSTAND_LOCK_HELD="1")
    assert run.returncode == 75, run.stderr


def test_a_second_start_waits_for_the_first_and_gives_up_cleanly(tmp_path: Path) -> None:
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "pid").write_text("999999 1 other\n", encoding="utf-8")
    with _held(tmp_path / "state" / "start.lock"):  # a first start is still running
        run = _run(tmp_path, "start")
        stop = _run(tmp_path, "stop", VM_LLM_STOP_WAIT_S="1")
        status = _run(tmp_path, "status")
    assert run.returncode == 75, run.stderr
    assert "start.lock" in run.stderr
    assert stop.returncode == 75
    assert status.returncode == 3
    assert (tmp_path / "state" / "pid").exists()  # nobody removed the first start's file


@pytest.mark.parametrize("content", ["-1 0 x", "0 0 x", "1 1 x", "abc def x", ""])
def test_a_bad_or_foreign_pid_file_is_never_signalled_and_is_cleaned_up(
    tmp_path: Path, content: str
) -> None:
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "pid").write_text(content + "\n", encoding="utf-8")
    run = _run(tmp_path, "stop")
    assert run.returncode == 0, run.stderr
    assert "not running" in run.stdout
    assert not (tmp_path / "state" / "pid").exists()


def test_a_live_process_that_is_not_our_server_is_not_killed(tmp_path: Path) -> None:
    victim = subprocess.Popen(["sleep", "30"])  # noqa: S607
    try:
        fields = Path(f"/proc/{victim.pid}/stat").read_text().rsplit(") ", 1)[1].split()
        (tmp_path / "state").mkdir()
        (tmp_path / "state" / "pid").write_text(f"{victim.pid} {fields[19]} x\n", encoding="utf-8")
        assert _run(tmp_path, "status").returncode == 3
        stop = _run(tmp_path, "stop")
        assert (
            stop.returncode == 2
        )  # alive with the recorded start time: maybe a server on another port
        assert "another VM_LLM_PORT" in stop.stderr
        assert victim.poll() is None
        assert (tmp_path / "state" / "pid").exists()  # never orphan a running server
    finally:
        victim.kill()
        victim.wait(timeout=10)


def test_a_start_that_times_out_while_the_launcher_still_works_kills_the_launcher(
    tmp_path: Path,
) -> None:
    # stand-in for pruefstand-lock while _serve waits for the lock or hashes the model: it never
    # becomes a server; after the timeout nothing of it may survive (a server could appear later)
    stub = tmp_path / "slow-lock"
    body = '#!/usr/bin/env bash\necho $$ > "$(dirname "$0")/stub.pid"\nsleep 120\n'
    stub.write_text(body)
    stub.chmod(0o755)
    run = _run(tmp_path, "start", VM_LLM_LOCK_CMD=str(stub), VM_LLM_READY_S="3")
    assert run.returncode == 1, run.stderr
    assert "not ready after 3s" in run.stderr
    stub_pid = int((tmp_path / "stub.pid").read_text())
    assert not Path(f"/proc/{stub_pid}").exists()
    assert not (tmp_path / "state" / "launcher").exists()
    assert not (tmp_path / "state" / "pid").exists()


def test_a_launcher_that_execs_into_another_program_is_still_killed_quickly(tmp_path: Path) -> None:
    # the launcher pid changes its command line along the exec chain (pruefstand-lock -> ... ->
    # timeout llama-server); identity is pid + start time + token, and start never waits for it
    stub = tmp_path / "exec-lock"
    stub.write_text('#!/usr/bin/env bash\necho $$ > "$(dirname "$0")/stub.pid"\nexec sleep 30\n')
    stub.chmod(0o755)
    began = time.monotonic()
    run = _run(tmp_path, "start", VM_LLM_LOCK_CMD=str(stub), VM_LLM_READY_S="2")
    took = time.monotonic() - began
    assert run.returncode == 1, run.stderr
    assert took < 15, took
    assert "another VM_LLM_PORT" not in run.stderr
    assert not Path(f"/proc/{int((tmp_path / 'stub.pid').read_text())}").exists()

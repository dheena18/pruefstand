"""vm_llm.sh: argument rules, the 127.0.0.1-only command, lock and check-slot refusals (D1200).

No server is started here (the ``live`` test in ``test_vm_llm_live.py`` does that); the lock tests
use the real ``infra/vm/pruefstand-lock`` against a temporary lock directory.
"""

import fcntl
import os
import socket
import subprocess
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
        "VM_LLM_PORT": str(_free_port()),
        "PRUEFSTAND_LOCK_DIR": str(tmp / "lock"),
        "PRUEFSTAND_CHECK_DIR": str(tmp / "check"),
    }
    return env | extra


def _run(tmp: Path, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
    cmd = ["bash", str(SCRIPT), *args]
    return subprocess.run(  # noqa: S603
        cmd, env=_env(tmp, **extra), capture_output=True, text=True, check=False, timeout=60
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


def test_start_is_refused_while_a_check_slot_is_busy(tmp_path: Path) -> None:
    with _held(tmp_path / "check" / "slot2.lock"):
        run = _run(tmp_path, "start")
    assert run.returncode == 75, run.stderr
    assert "check slot 2" in run.stderr


def test_a_missing_model_file_fails_before_any_server_starts(tmp_path: Path) -> None:
    run = _run(tmp_path, "start")
    assert run.returncode == 1
    assert "model file missing" in run.stderr
    assert _run(tmp_path, "status").returncode == 3


def test_a_model_file_of_the_wrong_size_is_refused(tmp_path: Path) -> None:
    models = tmp_path / "models"
    models.mkdir()
    (models / "Ministral-3-14B-Instruct-2512-Q4_K_M.gguf").write_bytes(b"GGUF")
    run = _run(tmp_path, "start")
    assert run.returncode == 1
    assert "wrong size" in run.stderr

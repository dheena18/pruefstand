"""Tests of the process handling of resolve_merge.sh (pytest in its own group, dies with it)."""

import os
import signal
import subprocess
import time
from pathlib import Path

from lead.leadtestenv import Lab

BRANCH = "feat/x"


def _resolve(lab: Lab, *args: str) -> subprocess.CompletedProcess[str]:
    return lab.run("resolve_merge.sh", str(lab.wt), BRANCH, *args)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_for(path: Path, seconds: float = 40) -> str:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists() and path.read_text(encoding="utf-8").strip():
            return path.read_text(encoding="utf-8").strip()
        time.sleep(0.2)
    msg = f"{path} never appeared"
    raise AssertionError(msg)


def _wait_dead(pid: int, seconds: float = 20) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.2)
    return False


def _start_sleeper(lab: Lab) -> tuple[subprocess.Popen[str], Path, int]:
    lab.write("theirs.txt", "t\n", where="other")
    lab.commit("theirs", where="other")
    marker = lab.root / "pytest.pid"
    code = (
        "import os, time\nfrom pathlib import Path\n\n\ndef test_sleep() -> None:\n"
        "    Path(os.environ['MARK']).write_text(str(os.getpid()))\n    time.sleep(120)\n"
    )
    lab.write("test_sleep.py", code)
    lab.commit("sleeper")
    proc = lab.popen(
        "resolve_merge.sh", str(lab.wt), BRANCH, "test_sleep.py",
        extra_env={"MARK": str(marker), "LEAD_TEST_TIMEOUT": "100"},
    )  # fmt: skip
    return proc, marker, int(_wait_for(marker))


def test_ctrl_c_of_the_script_kills_pytest(lab: Lab) -> None:
    proc, _, pytest_pid = _start_sleeper(lab)
    assert _alive(pytest_pid)
    proc.send_signal(signal.SIGINT)
    proc.communicate(timeout=60)
    assert proc.returncode == 130
    assert _wait_dead(pytest_pid), "pytest was orphaned"


def test_sigterm_of_the_script_kills_pytest_too(lab: Lab) -> None:
    proc, _, pytest_pid = _start_sleeper(lab)
    proc.send_signal(signal.SIGTERM)
    proc.communicate(timeout=60)
    assert proc.returncode == 143
    assert _wait_dead(pytest_pid), "pytest was orphaned"


def test_after_sigkill_a_rerun_refuses_while_pytest_lives_and_resumes_after(lab: Lab) -> None:
    proc, _, pytest_pid = _start_sleeper(lab)
    proc.kill()
    proc.communicate(timeout=60)
    assert _alive(pytest_pid)  # SIGKILL cannot be trapped: the orphan is bounded by its timeout
    second = _resolve(lab, "test_sleep.py")
    assert second.returncode == 1
    assert "still running" in second.stderr
    state = (lab.wt / ".git" / "lead-resolve-merge.state").read_text(encoding="utf-8")
    pgid = int(next(ln for ln in state.splitlines() if ln.startswith("child_pgid=")).split("=")[1])
    os.killpg(pgid, signal.SIGKILL)
    assert _wait_dead(pytest_pid)
    time.sleep(0.5)
    third = _resolve(lab)  # merge already committed; no tests this time
    assert third.returncode == 0, third.stderr + third.stdout
    assert lab.origin_has(BRANCH)

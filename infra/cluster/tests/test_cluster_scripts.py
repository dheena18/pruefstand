"""T3.1a CPU tests: ``start-ollama.sh``, ``stop-ollama.sh``, static rules (ADR-0018/0019, D228)."""

import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from gpu_testkit import CLUSTER_DIR, GPU_DIR, REPO, ClusterWorld, add_proc
from vm_testkit import Stubs

RUNNING = [("*api/tags*", '{"models":[]}', 0)]
REFUSED = [("*api/tags*", "", 7)]


def test_start_refuses_without_cluster_env(world: ClusterWorld) -> None:
    (world.bin_dir / "cluster.env").unlink()
    world.stubs.add("curl", REFUSED)
    res = world.script("start-ollama.sh")
    assert res.rc == 1
    assert "cluster.env" in res.err
    assert not world.stubs.calls("setsid")


def test_start_reuses_a_running_server_and_starts_nothing(world: ClusterWorld) -> None:
    world.stubs.add("curl", RUNNING)
    world.stubs.add("setsid")
    res = world.script("start-ollama.sh")
    assert res.rc == 0
    assert "already" in res.out
    assert not world.stubs.calls("setsid")
    assert world.script("start-ollama.sh").rc == 0  # a second call with the server healthy
    assert not world.stubs.calls("setsid")


def _wait_calls(world: ClusterWorld, name: str) -> list[str]:
    for _ in range(400):  # up to 20 s; returns as soon as the call shows up
        calls = world.stubs.calls(name)
        if calls:
            return calls
        time.sleep(0.05)
    return []


def test_start_launches_exactly_one_detached_owner_script(world: ClusterWorld) -> None:
    world.stubs.add("curl", REFUSED)
    world.stubs.add("setsid", default_rc=0)
    res = world.script("start-ollama.sh")
    assert res.rc == 0
    calls = _wait_calls(world, "setsid")  # the launch runs in the background
    assert calls == [f"setsid nohup {world.home}/start-ollama.sh"]
    assert world.log.exists()  # the output redirect to $OLLAMA_LOG
    forbidden = ("tmux", "ollama serve", "ollama runner")
    assert not any(
        f in line for line in world.stubs.log.read_text().splitlines() for f in forbidden
    )


def test_start_missing_owner_script_exits_1_and_starts_nothing(world: ClusterWorld) -> None:
    (world.home / "start-ollama.sh").unlink()
    world.stubs.add("curl", REFUSED)
    world.stubs.add("setsid", default_rc=0)
    res = world.script("start-ollama.sh")
    assert res.rc == 1
    assert "start-ollama.sh" in res.err
    assert not world.stubs.calls("setsid")


@pytest.mark.parametrize("arg", ["day", "night", "--force"])
def test_start_rejects_old_mode_arguments_with_usage(world: ClusterWorld, arg: str) -> None:
    world.stubs.add("curl", REFUSED)
    world.stubs.add("setsid", default_rc=0)
    res = world.script("start-ollama.sh", arg)
    assert res.rc == 2
    assert "usage" in res.err.lower()
    assert not world.stubs.calls("setsid")


def test_stop_kills_a_checked_ollama_serve_pid(world: ClusterWorld) -> None:
    world.add_serve(4242)
    world.stub_server([4242])
    world.stubs.add("kill", default_rc=0)
    res = world.script("stop-ollama.sh", STOP_WAIT_S="0")
    assert res.rc == 0
    assert world.stubs.calls("kill") == ["kill -TERM 4242"]


def test_stop_does_not_kill_a_pid_that_is_not_ollama_serve(world: ClusterWorld) -> None:
    add_proc(world.proc, 4242, ["python3", "-m", "http.server"])
    world.stub_server([4242])
    world.stubs.add("kill", default_rc=0)
    res = world.script("stop-ollama.sh", STOP_WAIT_S="0")
    assert res.rc == 1
    assert "not ollama serve" in res.err + res.out
    assert not world.stubs.calls("kill")


def test_stop_does_not_kill_when_nothing_listens_on_the_port(world: ClusterWorld) -> None:
    world.add_serve(4242)
    world.stub_server([4242], listening=False)
    world.stubs.add("kill", default_rc=0)
    res = world.script("stop-ollama.sh", STOP_WAIT_S="0")
    assert res.rc == 1
    assert not world.stubs.calls("kill")


def test_stop_without_a_server_is_a_noop(world: ClusterWorld) -> None:
    world.stub_server([])
    world.stubs.add("kill", default_rc=0)
    res = world.script("stop-ollama.sh", STOP_WAIT_S="0")
    assert res.rc == 0
    assert not world.stubs.calls("kill")


def test_no_pid_file_is_written_anywhere(world: ClusterWorld) -> None:
    world.stubs.add("curl", REFUSED)
    world.stubs.add("setsid", default_rc=0)
    world.script("start-ollama.sh")
    assert not list(world.root.rglob("*.pid"))
    for script in CLUSTER_DIR.glob("*.sh"):
        assert not re.search(r"\.pid\b|pidfile", script.read_text(encoding="utf-8")), script.name


def _code_lines(path: Path) -> list[str]:
    return [
        ln
        for ln in path.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    ]


def test_only_port_11434_no_spread_no_tmux_in_the_cluster_files() -> None:
    files = [*CLUSTER_DIR.glob("*.sh"), CLUSTER_DIR / "cluster.env.template"]
    for path in files:
        code = "\n".join(_code_lines(path))
        assert "OLLAMA_SCHED_SPREAD" not in code, path.name
        assert not re.search(r"\btmux\b", code), path.name
        assert set(re.findall(r"\b\d{5}\b", code)) <= {"11434"}, path.name
    template = (CLUSTER_DIR / "cluster.env.template").read_text(encoding="utf-8")
    assert set(re.findall(r"\b\d{5}\b", template)) == {"11434"}


def test_template_keys_match_the_expected_names() -> None:
    text = (CLUSTER_DIR / "cluster.env.template").read_text(encoding="utf-8")
    pairs = dict(ln.split("=", 1) for ln in text.splitlines() if ln and not ln.startswith("#"))
    assert pairs["OLLAMA_MODELS"] == "@MODELS_DIR@"
    assert pairs["OLLAMA_KV_CACHE_TYPE"] == "q8_0"
    assert pairs["OLLAMA_CONTEXT_LENGTH"] == "8192"
    assert pairs["OLLAMA_START_SCRIPT"] == "$HOME/start-ollama.sh"
    assert pairs["OLLAMA_LOG"] == "@LOG@"
    assert pairs["MODELS_MIN_FREE_GB"] == "2"
    assert pairs["CUDA_VISIBLE_DEVICES"] == "0,1"
    assert pairs["OLLAMA_MAX_LOADED_MODELS"] == "3"
    assert pairs["OLLAMA_NUM_PARALLEL"] == "4"
    assert pairs["OLLAMA_KEEP_ALIVE"] == "24h"
    assert pairs["OLLAMA_NOPRUNE"] == "1"
    assert pairs["OLLAMA_HOST"] == "127.0.0.1:11434"
    assert pairs["OLLAMA_FLASH_ATTENTION"] == "1"
    assert pairs["GENERATOR_TAG"] == "qwen3.8:27b-q8_0"
    assert not any(k.startswith(("OLLAMA_GPU", "RERANK")) for k in pairs)


def test_env_with_unexpected_syntax_is_refused(world: ClusterWorld) -> None:
    (world.bin_dir / "cluster.env").write_text("OLLAMA_HOST=127.0.0.1:11434; touch /tmp/x\n")
    world.stubs.add("curl", RUNNING)
    res = world.script("start-ollama.sh")
    assert res.rc == 1
    assert "cluster.env" in res.err


def test_shellcheck_clean(stubs: Stubs) -> None:
    tool = shutil.which("shellcheck")
    if tool is None:
        pytest.skip("shellcheck is not installed locally (CI has it)")
    files = [*CLUSTER_DIR.glob("*.sh"), *GPU_DIR.glob("*.sh"), *GPU_DIR.glob("lib/*.sh")]
    files += [GPU_DIR / "pruefstand-cluster"]
    proc = subprocess.run(  # noqa: S603
        [tool, "-x", "-P", "SCRIPTDIR", "-S", "info", *map(str, files)],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout


def _logical_lines(path: Path) -> list[str]:
    """Code lines with backslash continuations joined."""
    joined: list[str] = []
    carry = ""
    for line in _code_lines(path):
        if line.endswith("\\"):
            carry += line[:-1] + " "
        else:
            joined.append(carry + line)
            carry = ""
    return joined


def test_no_script_uses_the_a_and_b_or_c_pattern() -> None:
    """Newer shellcheck versions report SC2015 for ``A && B || C``; use if/then instead."""
    scripts = [*CLUSTER_DIR.glob("*.sh"), *GPU_DIR.glob("*.sh"), *GPU_DIR.glob("lib/*.sh")]
    for path in [*scripts, GPU_DIR / "pruefstand-cluster"]:
        for line in _logical_lines(path):
            assert not re.search(r"&&.*\|\|", line), f"{path.name}: {line.strip()}"


def test_the_a_and_b_or_c_check_sees_continuation_lines(tmp_path: Path) -> None:
    script = tmp_path / "x.sh"
    script.write_text("true && \\\n  true || false\n")
    assert any(re.search(r"&&.*\|\|", line) for line in _logical_lines(script))

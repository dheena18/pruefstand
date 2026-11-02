"""T3.1a CPU tests: ``cluster_ssh.sh``, the ``pruefstand-cluster`` wrapper and its installer."""

import fcntl
import os
from pathlib import Path

import pytest
from gpu_testkit import GPU_DIR, link_tools, run_script
from gpu_world import GpuWorld
from vm_testkit import Result

WRAPPER = GPU_DIR / "pruefstand-cluster"
INSTALL = GPU_DIR / "install-cluster-wrapper.sh"
BIN = "/data/dheena/pruefstand-bin"


def _wrap(gpu: GpuWorld, *args: str, held: bool = False, **env: str) -> Result:
    full = {"PRUEFSTAND_LOCK_DIR": str(gpu.lock_dir), "CLUSTER_SSH_HOST": "cairo-s101lp", **env}
    if held:
        full["PRUEFSTAND_LOCK_HELD"] = "1"
    return run_script(WRAPPER, *args, stubs=gpu.stubs, env=full)


def _ssh(gpu: GpuWorld) -> list[str]:
    return gpu.stubs.calls("ssh")


@pytest.mark.parametrize(
    "args",
    [
        (), ("reboot",), ("rm", "x; reboot"), ("rm", "$(id)"), ("pull",), ("pull", "a", "b"),
        ("pull", "-x"), ("status", "extra"), ("start-ollama", "day"), ("stop-ollama", "--force"),
        ("show", "A/B"), ("exec", "ls"),
    ],
)  # fmt: skip
def test_anything_outside_the_fixed_ops_exits_64_and_runs_nothing(
    gpu: GpuWorld, args: tuple[str, ...]
) -> None:
    assert _wrap(gpu, *args, held=True).rc == 64
    assert not _ssh(gpu)


@pytest.mark.parametrize("op", ["status", "show bge-m3"])
def test_read_ops_need_no_lock(gpu: GpuWorld, op: str) -> None:
    res = _wrap(gpu, *op.split())
    assert res.rc == 0, res.err
    assert len(_ssh(gpu)) == 1


@pytest.mark.parametrize("op", ["stop-ollama", "start-ollama", "pull bge-m3", "rm gemma3:12b"])
def test_mutating_ops_without_the_flag_exit_2_and_run_nothing(gpu: GpuWorld, op: str) -> None:
    res = _wrap(gpu, *op.split())
    assert res.rc == 2
    assert "run under the GPU lock (pruefstand-lock" in res.err
    assert not _ssh(gpu)


@pytest.mark.parametrize("op", ["stop-ollama", "pull bge-m3"])
def test_the_flag_alone_is_no_proof_the_lock_must_really_be_held(gpu: GpuWorld, op: str) -> None:
    res = _wrap(gpu, *op.split(), held=True)  # the temp lock file is free
    assert res.rc == 2
    assert not _ssh(gpu)


def test_mutating_ops_run_while_the_lock_is_really_held(gpu: GpuWorld) -> None:
    with (gpu.lock_dir / "gpu.lock").open("rb") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX)
        res = _wrap(gpu, "stop-ollama", held=True)
    assert res.rc == 0, res.err
    assert f"bash {BIN}/stop-ollama.sh" in _ssh(gpu)[0]


def test_ops_map_to_the_fixed_cluster_commands(gpu: GpuWorld) -> None:
    with (gpu.lock_dir / "gpu.lock").open("rb") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX)
        for op in (("start-ollama",), ("pull", "bge-m3"), ("rm", "gemma3:12b")):
            assert _wrap(gpu, *op, held=True).rc == 0
    _wrap(gpu, "status")
    _wrap(gpu, "show", "qwen3.8:27b-q8_0")
    cmds = [c.split("cairo-s101lp ", 1)[1] for c in _ssh(gpu)]
    assert cmds == [
        f"bash {BIN}/start-ollama.sh", f"bash {BIN}/ollama-op.sh pull bge-m3",
        f"bash {BIN}/ollama-op.sh rm gemma3:12b", f"bash {BIN}/status.sh",
        f"bash {BIN}/ollama-op.sh show qwen3.8:27b-q8_0",
    ]  # fmt: skip


def test_bin_dev_selects_the_dev_scripts_in_either_position(gpu: GpuWorld) -> None:
    assert _wrap(gpu, "--bin-dev", "status").rc == 0
    assert _wrap(gpu, "status", "--bin-dev").rc == 0
    assert all("/data/dheena/pruefstand-bin-dev/status.sh" in c for c in _ssh(gpu))
    assert len(_ssh(gpu)) == 2


def test_cluster_ssh_as_the_service_user_runs_ssh_directly(gpu: GpuWorld) -> None:
    res = _lib(gpu, "cluster_op status")
    assert res.rc == 0, res.err
    assert _ssh(gpu) == [
        f"ssh -o BatchMode=yes -o ConnectTimeout=15 cairo-s101lp bash {BIN}/status.sh"
    ]
    assert not gpu.stubs.calls("sudo")


def test_cluster_ssh_as_another_user_goes_through_the_sudo_wrapper(gpu: GpuWorld) -> None:
    gpu.stubs.add("sudo", [("*", "", 0)])
    res = _lib(gpu, "cluster_op pull bge-m3", PRUEFSTAND_SERVICE_USER="someone-else")
    assert res.rc == 0, res.err
    assert gpu.stubs.calls("sudo") == [
        "sudo -n -u pruefstand /usr/local/bin/pruefstand-cluster pull bge-m3"
    ]
    assert not _ssh(gpu)


def test_cluster_ssh_passes_bin_dev_to_the_wrapper(gpu: GpuWorld) -> None:
    gpu.stubs.add("sudo", [("*", "", 0)])
    _lib(gpu, "cluster_op status", PRUEFSTAND_SERVICE_USER="someone-else", PRUEFSTAND_BIN_DEV="1")
    assert gpu.stubs.calls("sudo") == [
        "sudo -n -u pruefstand /usr/local/bin/pruefstand-cluster status --bin-dev"
    ]


def test_cluster_ssh_validates_before_calling_anything(gpu: GpuWorld) -> None:
    gpu.stubs.add("sudo", [("*", "", 0)])
    assert _lib(gpu, "cluster_op rm 'x; reboot'").rc == 64
    assert _lib(gpu, "cluster_op reboot").rc == 64
    assert not _ssh(gpu)
    assert not gpu.stubs.calls("sudo")


def _lib(gpu: GpuWorld, call: str, **env: str) -> Result:
    harness = gpu.root / "harness.sh"
    harness.write_text(
        f'set -euo pipefail\n. "{GPU_DIR}/lib/cluster_ssh.sh"\n{call}\n', encoding="utf-8"
    )
    return run_script(harness, stubs=gpu.stubs, env=gpu.env(**env))


def test_the_sudoers_fragment_keeps_the_lock_flag_and_names_one_wrapper(gpu: GpuWorld) -> None:
    res = run_script(INSTALL, "--print-sudoers", stubs=gpu.stubs)
    assert res.rc == 0, res.err
    lines = res.out.splitlines()
    assert 'Defaults!/usr/local/bin/pruefstand-cluster env_keep += "PRUEFSTAND_LOCK_HELD"' in lines
    assert "%pruefstand ALL=(pruefstand) NOPASSWD: /usr/local/bin/pruefstand-cluster" in lines
    assert len([ln for ln in lines if ln and not ln.startswith("#")]) == 2


def test_install_refuses_without_root_and_changes_nothing(gpu: GpuWorld, tmp_path: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("running as root")
    res = run_script(INSTALL, stubs=gpu.stubs, env={"DESTDIR": ""})
    assert res.rc == 2
    assert "sudo" in res.err
    assert not list(tmp_path.glob("**/pruefstand-cluster*"))


def test_install_into_a_destdir_validates_the_sudoers_file_first(
    gpu: GpuWorld, tmp_path: Path
) -> None:
    dest = tmp_path / "root"
    gpu.stubs.add("visudo", [("-c -f *", "parsed OK", 0)])
    link_tools(gpu.stubs, "install", "chmod", "mkdir", "cat", "cp", "mv")
    res = run_script(INSTALL, stubs=gpu.stubs, env={"DESTDIR": str(dest)})
    assert res.rc == 0, res.err
    assert (dest / "usr/local/bin/pruefstand-cluster").read_text() == WRAPPER.read_text()
    assert (dest / "etc/sudoers.d/pruefstand-cluster").is_file()
    assert gpu.stubs.calls("visudo")[0].startswith("visudo -c -f ")


def test_a_sudoers_file_that_fails_visudo_is_not_installed(gpu: GpuWorld, tmp_path: Path) -> None:
    dest = tmp_path / "root"
    gpu.stubs.add("visudo", [("-c -f *", "syntax error", 1)])
    link_tools(gpu.stubs, "install", "chmod", "mkdir", "cat", "cp", "mv")
    res = run_script(INSTALL, stubs=gpu.stubs, env={"DESTDIR": str(dest)})
    assert res.rc != 0
    assert not (dest / "etc/sudoers.d/pruefstand-cluster").exists()


def test_the_wrapper_is_self_contained_and_only_the_tag_pattern_is_accepted() -> None:
    text = WRAPPER.read_text(encoding="utf-8")
    assert "source " not in text
    assert not any(line.strip().startswith(". ") for line in text.splitlines())
    assert "^[a-z0-9._:/-]+$" in text

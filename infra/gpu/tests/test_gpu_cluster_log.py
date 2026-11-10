"""T3.1e CPU tests: the ``log [N]`` op of the ``pruefstand-cluster`` wrapper and cluster_ssh.sh."""

import pytest
from gpu_testkit import GPU_DIR, rendered_wrapper, run_script
from gpu_world import ENTRIES, GpuWorld
from vm_testkit import Result

WRAPPER = GPU_DIR / "pruefstand-cluster"
BIN = "/data/example/pruefstand-bin"


def _wrap(gpu: GpuWorld, *args: str, **env: str) -> Result:
    allow = gpu.root / "cluster.allow"
    rows = [f"{tag}\t{e['disk_bytes']}" for tag, e in ENTRIES.items() if e["engine"] == "ollama"]
    allow.write_text("\n".join(rows) + "\n")
    full = {
        "PRUEFSTAND_LOCK_DIR": str(gpu.lock_dir),
        "CLUSTER_SSH_HOST": "cairo-s101lp",
        "PRUEFSTAND_CLUSTER_ALLOW": str(allow),
        **env,
    }
    return run_script(rendered_wrapper(gpu.root), *args, stubs=gpu.stubs, env=full)


def _cmds(gpu: GpuWorld) -> list[str]:
    return [c.split("cairo-s101lp ", 1)[1] for c in gpu.stubs.calls("ssh")]


def test_log_needs_no_lock_and_maps_to_the_fixed_script(gpu: GpuWorld) -> None:
    for args in (("log",), ("log", "5"), ("log", "1000"), ("--bin-dev", "log", "7")):
        assert _wrap(gpu, *args).rc == 0  # the lock file is free, PRUEFSTAND_LOCK_HELD unset
    assert _cmds(gpu) == [
        f"bash {BIN}/log-tail.sh 200", f"bash {BIN}/log-tail.sh 5",
        f"bash {BIN}/log-tail.sh 1000", f"bash {BIN}-dev/log-tail.sh 7",
    ]  # fmt: skip


def test_log_does_not_need_the_allow_list_or_maintenance(gpu: GpuWorld) -> None:
    res = _wrap(gpu, "log", PRUEFSTAND_CLUSTER_ALLOW=str(gpu.root / "absent"))
    assert res.rc == 0, res.err
    assert not (gpu.lock_dir / "MAINTENANCE").exists()


@pytest.mark.parametrize(
    "n", ["0", "1001", "99999", "-1", "abc", "1.5", "010", "1e3", "5;reboot", "$(id)", "", "+5"]
)
def test_a_bad_count_exits_64_and_runs_nothing(gpu: GpuWorld, n: str) -> None:
    res = _wrap(gpu, "log", n)
    assert res.rc == 64
    assert not gpu.stubs.calls("ssh")


@pytest.mark.parametrize("args", [("log", "5", "6"), ("log", "x", "y"), ("log", "bge-m3")])
def test_log_takes_at_most_one_count(gpu: GpuWorld, args: tuple[str, ...]) -> None:
    assert _wrap(gpu, *args).rc == 64
    assert not gpu.stubs.calls("ssh")


def test_the_ssh_command_never_carries_caller_text(gpu: GpuWorld) -> None:
    _wrap(gpu, "log", "12")
    assert _cmds(gpu) == [f"bash {BIN}/log-tail.sh 12"]


def _lib(gpu: GpuWorld, call: str, **env: str) -> Result:
    harness = gpu.root / "harness.sh"
    harness.write_text(
        f'set -euo pipefail\n. "{GPU_DIR}/lib/cluster_ssh.sh"\n{call}\n', encoding="utf-8"
    )
    return run_script(harness, stubs=gpu.stubs, env=gpu.env(**env))


def test_cluster_ssh_log_as_the_service_user_runs_ssh_directly(gpu: GpuWorld) -> None:
    assert _lib(gpu, "cluster_op log").rc == 0
    assert _lib(gpu, "cluster_op log 30").rc == 0
    assert _cmds(gpu) == [f"bash {BIN}/log-tail.sh 200", f"bash {BIN}/log-tail.sh 30"]


def test_cluster_ssh_log_as_another_user_goes_through_the_sudo_wrapper(gpu: GpuWorld) -> None:
    gpu.stubs.add("sudo", [("*", "", 0)])
    assert _lib(gpu, "cluster_op log 9", PRUEFSTAND_SERVICE_USER="someone-else").rc == 0
    assert gpu.stubs.calls("sudo") == [
        "sudo -n -u pruefstand /usr/local/bin/pruefstand-cluster log 9"
    ]
    assert not gpu.stubs.calls("ssh")


@pytest.mark.parametrize(
    "call", ["cluster_op log 0", "cluster_op log 1001", "cluster_op log x", "cluster_op log 1 2"]
)
def test_cluster_ssh_log_validates_before_calling_anything(gpu: GpuWorld, call: str) -> None:
    gpu.stubs.add("sudo", [("*", "", 0)])
    assert _lib(gpu, call).rc == 64
    assert not gpu.stubs.calls("ssh")
    assert not gpu.stubs.calls("sudo")


def test_the_sudoers_file_is_unchanged_by_the_log_op(gpu: GpuWorld) -> None:
    res = run_script(GPU_DIR / "install-cluster-wrapper.sh", "--print-sudoers", stubs=gpu.stubs)
    lines = [ln for ln in res.out.splitlines() if ln and not ln.startswith("#")]
    assert lines == [
        'Defaults!/usr/local/bin/pruefstand-cluster env_keep += "PRUEFSTAND_LOCK_HELD"',
        "%pruefstand ALL=(pruefstand) NOPASSWD: /usr/local/bin/pruefstand-cluster",
    ]

"""T0.7 CPU tests: ``vm_check.sh`` host, docker, tunnel, lock and data-root checks (stubs only)."""

from pathlib import Path

from vm_testkit import Runner
from vm_world import LISTEN, PF, World, check, raw


def test_healthy_vm_has_no_fail_and_every_documented_id(world: World, run_script: Runner) -> None:
    rows = check(world, run_script)
    ids = [
        *(
            "os",
            "ram",
            "cpu",
            "disk",
            "docker",
            "docker-group",
            "docker-gw",
            "proxy-net",
            "firewall",
        ),
        *("gh-scope", "users", "lock-dir", "data-root", "data-root-rw", "ssh-key", "tunnel"),
        *("tunnel-reboot", "host-reboot", "vscode"),
    ]
    assert list(rows) == ids
    failing = {k: v for k, v in rows.items() if v[0] == "FAIL"}
    assert not failing
    for ident in set(ids) - {"tunnel-reboot", "host-reboot", "vscode"}:
        assert rows[ident][0] == "PASS", (ident, rows[ident])
    for ident in ("tunnel-reboot", "host-reboot", "vscode"):
        assert rows[ident][0] == "WARN"
        assert "--confirm" in rows[ident][1]


def test_exit_code_reflects_fail(world: World, run_script: Runner) -> None:
    assert raw(world, run_script).rc == 0
    world.override("docker", ("info -f*", "[name=rootless]", 0))
    assert raw(world, run_script).rc == 1


def test_confirmations_are_recorded(world: World, run_script: Runner) -> None:
    assert raw(world, run_script, "--confirm", "vscode").rc == 0
    assert check(world, run_script, "vscode")["vscode"][0] == "PASS"


def test_os_accepts_24_04_and_later_but_not_older(
    world: World, run_script: Runner, tmp_path: Path
) -> None:
    rel = tmp_path / "os-release"
    rel.write_text('ID=ubuntu\nVERSION_ID="26.04"\n', encoding="utf-8")
    assert check(world, run_script, "os")["os"][0] == "WARN"
    rel.write_text('ID=ubuntu\nVERSION_ID="22.04"\n', encoding="utf-8")
    assert check(world, run_script, "os")["os"][0] == "FAIL"
    rel.write_text('ID=debian\nVERSION_ID="12"\n', encoding="utf-8")
    assert check(world, run_script, "os")["os"][0] == "FAIL"


def test_resource_checks(world: World, run_script: Runner, tmp_path: Path) -> None:
    (tmp_path / "meminfo").write_text("MemTotal:  16000000 kB\n", encoding="utf-8")
    world.put("nproc", [("*", "4", 0)])
    rows = check(world, run_script, "ram", "cpu")
    assert rows["ram"][0] == "FAIL"
    assert rows["cpu"][0] == "FAIL"


def test_docker_rootless_fails(world: World, run_script: Runner) -> None:
    world.override("docker", ("info -f*", "[name=seccomp name=rootless]", 0))
    assert check(world, run_script, "docker")["docker"][0] == "FAIL"


def test_docker_group_with_third_member_fails(world: World, run_script: Runner) -> None:
    world.override("getent", ("group docker", "docker:x:999:alice,pruefstand,mallory", 0))
    status, detail = check(world, run_script, "docker-group")["docker-group"]
    assert status == "FAIL"
    assert "mallory" in detail


def test_tunnel_pass_fail_and_warn_cases(world: World, run_script: Runner, tmp_path: Path) -> None:
    assert check(world, run_script, "tunnel")["tunnel"][0] == "PASS"
    world.override("curl", ("*", "000", 7))
    assert check(world, run_script, "tunnel")["tunnel"][0] == "FAIL"
    world.override("curl", ("*127.0.0.1:11434/api/tags*", "200", 0))
    world.put(
        "ss",
        [("*", LISTEN + '\nLISTEN 0 128 127.0.0.1:21434 0.0.0.0:* users:(("ssh",pid=12,fd=5))', 0)],
    )
    assert check(world, run_script, "tunnel")["tunnel"][0] == "WARN"
    world.put("ss", [("*", LISTEN.replace("172.17.0.1:11434", "0.0.0.0:11434"), 0)])
    assert check(world, run_script, "tunnel")["tunnel"][0] == "FAIL"
    world.put("ss", [("*", LISTEN, 0)])
    (tmp_path / "env").write_text(
        "OLLAMA_GPU0_URL=http://127.0.0.1:11434\nOLLAMA_GPU1_URL=http://127.0.0.1:11435\n",
        encoding="utf-8",
    )
    assert check(world, run_script, "tunnel")["tunnel"][0] == "WARN"
    (tmp_path / "env").write_text(
        "OLLAMA_GPU0_URL=https://public.example.org:11434\nOLLAMA_GPU1_URL=https://public.example.org:11434\n",
        encoding="utf-8",
    )
    assert check(world, run_script, "tunnel")["tunnel"][0] == "FAIL"


def test_tunnel_user_unit_is_a_fail(world: World, run_script: Runner) -> None:
    world.override("systemctl", ("show -p User --value pruefstand-tunnel", "", 0))
    assert check(world, run_script, "tunnel")["tunnel"][0] == "FAIL"


def test_lock_dir_maintenance_is_a_warning_and_wrong_mode_a_fail(
    world: World, run_script: Runner
) -> None:
    assert check(world, run_script, "lock-dir")["lock-dir"][0] == "PASS"
    (Path(world.env["PRUEFSTAND_LOCK_DIR"]) / "MAINTENANCE").touch()
    status, detail = check(world, run_script, "lock-dir")["lock-dir"]
    assert status == "WARN"
    assert "maintenance set" in detail
    world.override("stat", ("*gpu.lock", f"666 {PF}", 0))
    assert check(world, run_script, "lock-dir")["lock-dir"][0] == "FAIL"


def test_data_root_low_space_warns_and_fstab_line_fails(
    world: World, run_script: Runner, tmp_path: Path
) -> None:
    ten_gb = "Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/x 1 1 10485760 1% /"
    world.override("df", ("*", ten_gb, 0))
    status, detail = check(world, run_script, "data-root")["data-root"]
    assert status == "WARN"
    assert "free" in detail
    world.override("df", ("*-Pk *data", ten_gb.replace("10485760", "400000000"), 0))
    (tmp_path / "fstab").write_text(
        f"srv:/x {world.env['PRUEFSTAND_DATA_ROOT']} nfs defaults 0 0\n", encoding="utf-8"
    )
    assert check(world, run_script, "data-root")["data-root"][0] == "FAIL"


def test_ssh_key_checks(world: World, run_script: Runner, tmp_path: Path) -> None:
    assert check(world, run_script, "ssh-key")["ssh-key"][0] == "PASS"
    (tmp_path / "ownerhome" / ".ssh" / "id_ed25519_cluster").touch()
    assert check(world, run_script, "ssh-key")["ssh-key"][0] == "FAIL"

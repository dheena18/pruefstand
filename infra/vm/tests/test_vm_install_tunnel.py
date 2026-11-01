"""T0.7 CPU tests: ``install-tunnel.sh`` guards, backup and rollback (stubs only)."""

from pathlib import Path

from vm_testkit import VM_DIR, Result, Runner, Stubs

UNIT_NAME = "pruefstand-tunnel.service"
REPO_UNIT = (VM_DIR / UNIT_NAME).read_text(encoding="utf-8")
DOCKER0 = "inet 172.17.0.1/16"
BOTH = (
    'LISTEN 0 128 127.0.0.1:11434 0.0.0.0:* users:(("ssh",pid=1,fd=5))\n'
    'LISTEN 0 128 172.17.0.1:11434 0.0.0.0:* users:(("ssh",pid=1,fd=6))'
)
NOT_SSH = BOTH.replace('"ssh"', '"python3"')


def _stubs(
    stubs: Stubs,
    *,
    fw: str = "active",
    gateway_rc: int = 0,
    docker0: str = DOCKER0,
    restart_rc: int = 0,
    listen: str = BOTH,
    need_reload: str = "no",
) -> None:
    stubs.add("id", [("-u", "0", 0)])
    stubs.add("autossh", [("*", "", 0)])
    stubs.add("fwbin", [("--check-gateway", "", gateway_rc)])
    stubs.add("ip", [("-4 addr show docker0", docker0, 0)])
    stubs.add("ss", [("*", listen, 0)])
    stubs.add(
        "systemctl",
        [
            ("is-active pruefstand-firewall", fw, 0 if fw == "active" else 3),
            ("is-active pruefstand-tunnel", "active", 0),
            ("show -p NeedDaemonReload --value pruefstand-tunnel", need_reload, 0),
            ("restart pruefstand-tunnel", "", restart_rc),
            ("*", "", 0),
        ],
    )


def _run(run_script: Runner, stubs: Stubs, unit_dir: Path) -> Result:
    args = ["--unit-dir", unit_dir, "--firewall-bin", stubs.bin / "fwbin"]
    return run_script("install-tunnel.sh", *args, env={"TUNNEL_WAIT_S": "1"})


def _unit_dir(tmp_path: Path, content: str | None = "OLD\n", bak: str | None = None) -> Path:
    unit_dir = tmp_path / "units"
    unit_dir.mkdir()
    if content is not None:
        (unit_dir / UNIT_NAME).write_text(content, encoding="utf-8")
    if bak is not None:
        (unit_dir / f"{UNIT_NAME}.bak").write_text(bak, encoding="utf-8")
    return unit_dir


def _text(unit_dir: Path, name: str = UNIT_NAME) -> str:
    return (unit_dir / name).read_text(encoding="utf-8")


def test_refuses_when_firewall_is_not_active(
    run_script: Runner, stubs: Stubs, tmp_path: Path
) -> None:
    _stubs(stubs, fw="inactive")
    unit_dir = _unit_dir(tmp_path)
    res = _run(run_script, stubs, unit_dir)
    assert res.rc == 3
    assert "setup-proxy-net.sh" in res.err
    assert _text(unit_dir) == "OLD\n"


def test_refuses_when_the_gateway_rules_are_not_in_place(
    run_script: Runner, stubs: Stubs, tmp_path: Path
) -> None:
    _stubs(stubs, gateway_rc=1)
    unit_dir = _unit_dir(tmp_path)
    res = _run(run_script, stubs, unit_dir)
    assert res.rc == 3
    assert "--check-gateway" in res.err
    assert _text(unit_dir) == "OLD\n"


def test_docker0_check_is_anchored(run_script: Runner, stubs: Stubs, tmp_path: Path) -> None:
    _stubs(stubs, docker0="inet 172.17.0.15/16")
    assert _run(run_script, stubs, _unit_dir(tmp_path)).rc == 3


def test_success_installs_and_removes_the_backup(
    run_script: Runner, stubs: Stubs, tmp_path: Path
) -> None:
    _stubs(stubs)
    unit_dir = _unit_dir(tmp_path)
    res = _run(run_script, stubs, unit_dir)
    assert res.rc == 0, res.err + res.out
    assert _text(unit_dir) == REPO_UNIT
    assert not (unit_dir / f"{UNIT_NAME}.bak").exists()


def test_failed_restart_restores_the_old_unit(
    run_script: Runner, stubs: Stubs, tmp_path: Path
) -> None:
    _stubs(stubs, restart_rc=1)
    unit_dir = _unit_dir(tmp_path)
    assert _run(run_script, stubs, unit_dir).rc != 0
    assert _text(unit_dir) == "OLD\n"
    calls = stubs.calls("systemctl")
    assert len([c for c in calls if "restart pruefstand-tunnel" in c]) == 2
    assert len([c for c in calls if "daemon-reload" in c]) == 2


def test_missing_second_listener_rolls_back(
    run_script: Runner, stubs: Stubs, tmp_path: Path
) -> None:
    _stubs(stubs, listen=BOTH.splitlines()[0])
    unit_dir = _unit_dir(tmp_path)
    res = _run(run_script, stubs, unit_dir)
    assert res.rc != 0
    assert "172.17.0.1:11434" in res.err
    assert _text(unit_dir) == "OLD\n"


def test_listeners_must_belong_to_ssh(run_script: Runner, stubs: Stubs, tmp_path: Path) -> None:
    _stubs(stubs, listen=NOT_SSH)
    assert _run(run_script, stubs, _unit_dir(tmp_path)).rc != 0


def test_a_stale_backup_is_never_restored(run_script: Runner, stubs: Stubs, tmp_path: Path) -> None:
    _stubs(stubs, restart_rc=1)
    unit_dir = _unit_dir(tmp_path, content=None, bak="STALE\n")
    assert _run(run_script, stubs, unit_dir).rc != 0
    assert _text(unit_dir) != "STALE\n"


def test_up_to_date_unit_still_waits_for_the_listeners(
    run_script: Runner, stubs: Stubs, tmp_path: Path
) -> None:
    _stubs(stubs, listen=BOTH.splitlines()[0])
    unit_dir = _unit_dir(tmp_path, content=REPO_UNIT)
    assert _run(run_script, stubs, unit_dir).rc == 1
    _stubs(stubs)
    assert _run(run_script, stubs, unit_dir).rc == 0


def test_up_to_date_run_reloads_and_restarts_after_an_interrupted_install(
    run_script: Runner, stubs: Stubs, tmp_path: Path
) -> None:
    _stubs(stubs, need_reload="yes")
    unit_dir = _unit_dir(tmp_path, content=REPO_UNIT, bak="STALE\n")
    res = _run(run_script, stubs, unit_dir)
    assert res.rc == 0, res.err + res.out
    calls = stubs.calls("systemctl")
    assert any("daemon-reload" in c for c in calls)
    assert any("restart pruefstand-tunnel" in c for c in calls)
    assert not (unit_dir / f"{UNIT_NAME}.bak").exists(), "stale backup removed after success"


def test_up_to_date_run_without_pending_reload_does_not_restart(
    run_script: Runner, stubs: Stubs, tmp_path: Path
) -> None:
    _stubs(stubs, need_reload="no")
    assert _run(run_script, stubs, _unit_dir(tmp_path, content=REPO_UNIT)).rc == 0
    assert not [c for c in stubs.calls("systemctl") if "restart pruefstand-tunnel" in c]


def test_firewall_bin_env_var_is_ignored(run_script: Runner, stubs: Stubs, tmp_path: Path) -> None:
    _stubs(stubs)
    env = {"TUNNEL_WAIT_S": "1", "PRUEFSTAND_FIREWALL_BIN": str(stubs.bin / "fwbin")}
    unit_dir = _unit_dir(tmp_path)
    res = run_script("install-tunnel.sh", "--unit-dir", unit_dir, env=env)
    assert res.rc == 3
    assert "--check-gateway" in res.err

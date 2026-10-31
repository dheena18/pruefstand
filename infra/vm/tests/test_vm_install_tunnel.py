"""T0.7 CPU tests: ``install-tunnel.sh`` guards, backup and rollback (M1, M2; stubs only)."""

from pathlib import Path

from vm_testkit import VM_DIR, Result, Runner, Stubs

REPO_UNIT = (VM_DIR / "pruefstand-tunnel.service").read_text(encoding="utf-8")
BOTH = "LISTEN 0 128 127.0.0.1:11434 0.0.0.0:*\nLISTEN 0 128 172.17.0.1:11434 0.0.0.0:*"


DOCKER0 = "inet 172.17.0.1/16"


def _stubs(stubs: Stubs, *, fw: str = "active", docker0: str = DOCKER0, restart_rc: int = 0,
           tunnel: str = "active", listen: str = BOTH) -> None:  # fmt: skip
    stubs.add("id", [("-u", "0", 0)])
    stubs.add("autossh", [("*", "", 0)])
    stubs.add("ip", [("-4 addr show docker0", docker0, 0)])
    stubs.add("ss", [("*", listen, 0)])
    stubs.add(
        "systemctl",
        [
            ("is-active pruefstand-firewall", fw, 0 if fw == "active" else 3),
            ("is-active pruefstand-tunnel", tunnel, 0 if tunnel == "active" else 3),
            ("restart pruefstand-tunnel", "", restart_rc),
            ("*", "", 0),
        ],
    )


def _run(run_script: Runner, unit_dir: Path, wait: str = "1") -> Result:
    return run_script("install-tunnel.sh", "--unit-dir", unit_dir, env={"TUNNEL_WAIT_S": wait})


def _old_unit(tmp_path: Path) -> Path:
    unit_dir = tmp_path / "units"
    unit_dir.mkdir()
    (unit_dir / "pruefstand-tunnel.service").write_text("OLD\n", encoding="utf-8")
    return unit_dir


def test_refuses_when_firewall_is_not_active(
    run_script: Runner, stubs: Stubs, tmp_path: Path
) -> None:
    _stubs(stubs, fw="inactive")
    unit_dir = _old_unit(tmp_path)
    res = _run(run_script, unit_dir)
    assert res.rc == 3
    assert "setup-proxy-net.sh" in res.err
    assert (unit_dir / "pruefstand-tunnel.service").read_text(encoding="utf-8") == "OLD\n"


def test_docker0_check_is_anchored(run_script: Runner, stubs: Stubs, tmp_path: Path) -> None:
    _stubs(stubs, docker0="inet 172.17.0.15/16")
    assert _run(run_script, _old_unit(tmp_path)).rc == 3


def test_success_backs_up_installs_and_waits_for_both_listeners(
    run_script: Runner, stubs: Stubs, tmp_path: Path
) -> None:
    _stubs(stubs)
    unit_dir = _old_unit(tmp_path)
    res = _run(run_script, unit_dir)
    assert res.rc == 0, res.err + res.out
    assert (unit_dir / "pruefstand-tunnel.service").read_text(encoding="utf-8") == REPO_UNIT
    assert (unit_dir / "pruefstand-tunnel.service.bak").read_text(encoding="utf-8") == "OLD\n"


def test_failed_restart_restores_the_old_unit(
    run_script: Runner, stubs: Stubs, tmp_path: Path
) -> None:
    _stubs(stubs, restart_rc=1)
    unit_dir = _old_unit(tmp_path)
    res = _run(run_script, unit_dir)
    assert res.rc != 0
    assert (unit_dir / "pruefstand-tunnel.service").read_text(encoding="utf-8") == "OLD\n"
    calls = stubs.calls("systemctl")
    assert len([c for c in calls if "restart pruefstand-tunnel" in c]) == 2
    assert len([c for c in calls if "daemon-reload" in c]) == 2


def test_missing_second_listener_counts_as_failure_and_rolls_back(
    run_script: Runner, stubs: Stubs, tmp_path: Path
) -> None:
    _stubs(stubs, listen="LISTEN 0 128 127.0.0.1:11434 0.0.0.0:*")
    unit_dir = _old_unit(tmp_path)
    res = _run(run_script, unit_dir)
    assert res.rc != 0
    assert (unit_dir / "pruefstand-tunnel.service").read_text(encoding="utf-8") == "OLD\n"
    assert "172.17.0.1:11434" in res.err

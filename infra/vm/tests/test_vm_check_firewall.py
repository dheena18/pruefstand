"""T0.7 CPU tests: ``vm_check.sh`` firewall, ``gh-scope`` and ``--restart-drill`` (stubs only)."""

import fcntl
from pathlib import Path

from vm_testkit import VM_DIR, Runner
from vm_world import IPT_USER, World, check, raw


def test_gh_scope(world: World, run_script: Runner) -> None:
    assert check(world, run_script, "gh-scope")["gh-scope"][0] == "PASS"
    world.override("gh", ("api repos/dheena18/pruefstand-gate*", '{"name":"pruefstand-gate"}', 0))
    assert check(world, run_script, "gh-scope")["gh-scope"][0] == "FAIL"
    world.override("gh", ("auth token", "gho_classicoauth", 0))
    assert check(world, run_script, "gh-scope")["gh-scope"][0] == "FAIL"


def test_gh_token_is_never_printed(world: World, run_script: Runner) -> None:
    res = raw(world, run_script)
    assert "TESTONLY" not in res.out + res.err


def test_firewall_failures(world: World, run_script: Runner) -> None:
    assert check(world, run_script, "firewall")["firewall"][0] == "PASS"
    world.override("systemctl", ("is-active pruefstand-firewall", "inactive", 3))
    assert check(world, run_script, "firewall")["firewall"][0] == "FAIL"
    world.override(
        "systemctl",
        ("is-active pruefstand-firewall", "active", 0),
        ("is-enabled nftables", "enabled", 0),
    )
    assert check(world, run_script, "firewall")["firewall"][0] == "FAIL"
    world.override("systemctl", ("is-enabled nftables", "disabled", 1))
    swapped = "\n".join(
        IPT_USER.splitlines()[:1]
        + IPT_USER.splitlines()[2:3]
        + IPT_USER.splitlines()[1:2]
        + IPT_USER.splitlines()[3:]
    )
    world.override("iptables", ("*-S DOCKER-USER", swapped, 0))
    assert check(world, run_script, "firewall")["firewall"][0] == "FAIL"


def test_firewall_behavioural_probes(world: World, run_script: Runner) -> None:
    world.override("docker", ("run*--network bridge*", "200", 0))
    status, detail = check(world, run_script, "firewall")["firewall"]
    assert status == "FAIL"
    assert "bridge" in detail
    world.override(
        "docker", ("run*--network bridge*", "000", 28), ("run*--network proxy-egress*", "000", 28)
    )
    assert check(world, run_script, "firewall")["firewall"][0] == "FAIL"


def test_plain_run_never_restarts_docker(world: World, run_script: Runner) -> None:
    raw(world, run_script)
    assert not [c for c in world.stubs.calls("systemctl") if "restart docker" in c]
    assert not [c for c in world.stubs.calls("sudo") if "restart docker" in c]


def test_restart_drill_refuses_while_lock_is_held(world: World, run_script: Runner) -> None:
    lock = Path(world.env["PRUEFSTAND_LOCK_DIR"]) / "gpu.lock"
    with lock.open("rb") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX)
        res = raw(world, run_script, "--restart-drill")
    assert res.rc == 75
    assert "gpu.lock busy" in res.err + res.out
    assert not [c for c in world.stubs.calls("systemctl") if "restart docker" in c]


def test_restart_drill_restarts_docker_once_and_rechecks_firewall(
    world: World, run_script: Runner
) -> None:
    res = raw(world, run_script, "--restart-drill")
    assert res.rc == 0, res.err + res.out
    assert len([c for c in world.stubs.calls("systemctl") if "restart docker" in c]) == 1
    assert "CHECK firewall PASS" in res.out


def test_docker_is_restarted_in_exactly_one_place() -> None:
    text = (VM_DIR / "vm_check.sh").read_text(encoding="utf-8")
    assert text.count("restart docker") == 1

"""T0.7 CPU tests: ``vm_check.sh`` firewall, ``gh-scope`` and ``--restart-drill`` (stubs only)."""

import fcntl
from pathlib import Path

from vm_testkit import VM_DIR, Runner
from vm_world import IPT_INPUT, IPT_USER, World, check, raw


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


def test_public_cluster_endpoint_is_a_warning_not_a_blocked_expectation(
    world: World, run_script: Runner
) -> None:
    world.override("getent", ("ahostsv4 cluster.invalid", "203.0.113.5 STREAM cluster.invalid", 0))
    status, detail = check(world, run_script, "firewall")["firewall"]
    assert status == "WARN"
    assert "cluster endpoint is public; not blockable by RFC1918 rules" in detail
    world.override("docker", ("run*203.0.113.5*", "000", 0))  # would be "reached" if it were probed
    assert check(world, run_script, "firewall")["firewall"][0] == "WARN"


def test_dns_failure_is_not_proof_of_a_drop(world: World, run_script: Runner) -> None:
    world.override("docker", ("run*--network bridge*", "000", 6))
    status, detail = check(world, run_script, "firewall")["firewall"]
    assert status != "PASS"
    assert "bridge" in detail


def test_only_a_timeout_proves_a_drop(world: World, run_script: Runner) -> None:
    world.override("docker", ("run*--network bridge*", "000", 7))
    assert check(world, run_script, "firewall")["firewall"][0] == "FAIL"


def test_probe_image_by_tag_warns(world: World, run_script: Runner) -> None:
    status, detail = check(
        world, run_script, "firewall", env={"PROBE_IMAGE": "curlimages/curl:8.11.1"}
    )["firewall"]
    assert status == "WARN"
    assert "digest" in detail


def test_missing_input_jump_and_misordered_input_chain_fail(
    world: World, run_script: Runner
) -> None:
    world.override("iptables", ("*-C INPUT*", "", 1))
    status, detail = check(world, run_script, "firewall")["firewall"]
    assert status == "FAIL"
    assert "jump" in detail
    lines = IPT_INPUT.splitlines()
    swapped = "\n".join([lines[0], lines[3], lines[2], *lines[1:2], *lines[4:]])
    world.override("iptables", ("*-C INPUT*", "", 0), ("*-S PRUEFSTAND-INPUT", swapped, 0))
    assert check(world, run_script, "firewall")["firewall"][0] == "FAIL"


def test_probe_containers_and_networks_are_cleaned_up(world: World, run_script: Runner) -> None:
    raw(world, run_script, "firewall")
    docker = world.stubs.calls("docker")
    assert any(c.startswith("docker rm -f pf-probe-cf") for c in docker)
    created = [c.split()[-1] for c in docker if c.startswith("docker network create")]
    removed = [c.split()[-1] for c in docker if c.startswith("docker network rm")]
    assert created
    assert sorted(created) == sorted(removed)


def test_restart_drill_refuses_with_running_containers_unless_yes(
    world: World, run_script: Runner
) -> None:
    world.override("docker", ("ps -q*", "abc123", 0))
    res = raw(world, run_script, "--restart-drill")
    assert res.rc == 2
    assert "running containers" in res.err
    assert not [c for c in world.stubs.calls("systemctl") if "restart docker" in c]
    assert raw(world, run_script, "--restart-drill", "--yes").rc == 0


def test_restart_drill_fails_when_the_firewall_unit_did_not_restart(
    world: World, run_script: Runner
) -> None:
    world.override(
        "systemctl",
        ("show -p ActiveEnterTimestampMonotonic --value pruefstand-firewall", "12345", 0),
    )
    res = raw(world, run_script, "--restart-drill")
    assert res.rc == 1
    assert "CHECK firewall FAIL" in res.out
    assert "did not restart" in res.out


def test_missing_conntrack_return_in_docker_user_fails(world: World, run_script: Runner) -> None:
    no_ret = "\n".join(
        ln for ln in IPT_USER.splitlines() if "RETURN" not in ln or "ctstate" not in ln
    )
    world.override("iptables", ("*-S DOCKER-USER", no_ret, 0))
    status, detail = check(world, run_script, "firewall")["firewall"]
    assert status == "FAIL"
    assert "conntrack" in detail


def test_accept_without_the_fixed_bridge_fails(world: World, run_script: Runner) -> None:
    world.override("iptables", ("*-S DOCKER-USER", IPT_USER.replace(" -i pfproxy0", ""), 0))
    assert check(world, run_script, "firewall")["firewall"][0] == "FAIL"


def test_demo_egress_without_dns_warns_with_the_hint(world: World, run_script: Runner) -> None:
    world.override("docker", ("exec*nslookup*", "", 1))
    status, detail = check(world, run_script, "firewall")["firewall"]
    assert status == "WARN"
    assert "dns:" in detail


def test_proxy_net_wants_the_fixed_bridge_name(world: World, run_script: Runner) -> None:
    world.override("docker", ("network inspect proxy-egress*", "10.231.0.0/24 false br-abc", 0))
    assert check(world, run_script, "proxy-net")["proxy-net"][0] == "FAIL"

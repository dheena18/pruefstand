"""T0.7 CPU tests: ``setup-proxy-net.sh`` and ``pruefstand-firewall.sh`` (D242, N4.2, P2.2)."""

import os
from pathlib import Path

from vm_testkit import Runner, Stubs

GW = "172.17.0.1"
ACCEPT = "-s 10.231.0.0/24 -d 172.17.0.1 -p tcp --dport 11434 -j ACCEPT"
DROP = "-d 172.17.0.1 -p tcp --dport 11434 -j DROP"
ROUTES = "default via 192.168.1.1 dev ens3\n172.17.0.0/16 dev docker0\n192.168.1.0/24 dev ens3"


def _iptables(stubs: Stubs, *, present: bool) -> None:
    rc = 0 if present else 1
    stubs.add("iptables", [("*-C *", "", rc), ("*-L PRUEFSTAND-INPUT*", "", rc), ("*", "", 0)])


def _plans(out: str) -> list[str]:
    return [ln.removeprefix("PLAN ") for ln in out.splitlines() if ln.startswith("PLAN ")]


def _chain_rules(plans: list[str], chain: str) -> list[str]:
    rules = []
    for ln in plans:
        words = ln.split()
        if "iptables" in words and ("-I" in words or "-A" in words) and chain in words:
            rules.append(ln)
    return rules


# --- pruefstand-firewall.sh -----------------------------------------------------------
def test_firewall_dry_run_orders_accept_before_drop_in_both_chains(
    run_script: Runner, stubs: Stubs
) -> None:
    _iptables(stubs, present=False)
    res = run_script("pruefstand-firewall.sh", "--dry-run")
    assert res.rc == 0, res.err
    plans = _plans(res.out)
    for chain in ("DOCKER-USER", "PRUEFSTAND-INPUT"):
        rules = _chain_rules(plans, chain)
        accept = next(i for i, r in enumerate(rules) if ACCEPT in r)
        drop = next(i for i, r in enumerate(rules) if DROP in r)
        assert accept < drop, chain
    assert any("-I INPUT" in p and "-j PRUEFSTAND-INPUT" in p for p in plans)


def test_firewall_dry_run_demo_rules(run_script: Runner, stubs: Stubs) -> None:
    _iptables(stubs, present=False)
    plans = _plans(run_script("pruefstand-firewall.sh", "--dry-run").out)
    user = "\n".join(_chain_rules(plans, "DOCKER-USER"))
    for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"):
        assert f"-s 10.233.0.0/24 -d {net} -j DROP" in user
    assert "10.232.0.0/24" not in user, "demo-net is --internal: no DOCKER-USER rule for it"
    assert "RETURN" not in "\n".join(plans)
    inp = "\n".join(_chain_rules(plans, "PRUEFSTAND-INPUT"))
    assert "-s 10.232.0.0/24 -j DROP" in inp
    assert "-s 10.233.0.0/24 -j DROP" in inp


def test_firewall_flushes_only_its_own_chain_and_nothing_else(
    run_script: Runner, stubs: Stubs
) -> None:
    _iptables(stubs, present=False)
    res = run_script("pruefstand-firewall.sh", "--dry-run")
    for ln in _plans(res.out):
        words = ln.split()
        if "-F" in words:
            assert words[words.index("-F") + 1] == "PRUEFSTAND-INPUT"
        assert "-X" not in words
        assert "-t" not in words
        assert "-P" not in words
        assert "restore" not in ln
        assert "flush ruleset" not in ln


def test_firewall_second_run_inserts_nothing(run_script: Runner, stubs: Stubs) -> None:
    _iptables(stubs, present=True)
    res = run_script("pruefstand-firewall.sh", "--dry-run")
    assert res.rc == 0
    assert _plans(res.out) == []
    assert "no changes" in res.out


def test_firewall_check_mode(run_script: Runner, stubs: Stubs) -> None:
    _iptables(stubs, present=True)
    assert run_script("pruefstand-firewall.sh", "--check").rc == 0
    _iptables(stubs, present=False)
    res = run_script("pruefstand-firewall.sh", "--check")
    assert res.rc == 1
    assert "missing" in res.out


def test_firewall_real_run_needs_root(run_script: Runner, stubs: Stubs) -> None:
    if os.geteuid() == 0:
        return
    _iptables(stubs, present=False)
    assert run_script("pruefstand-firewall.sh").rc == 2
    assert all("-I" not in c and "-A" not in c for c in stubs.calls("iptables"))


# --- setup-proxy-net.sh ---------------------------------------------------------------
def _net_stubs(stubs: Stubs, *, exists: bool, routes: str = ROUTES) -> None:
    inspect_rc = 0 if exists else 1
    stubs.add(
        "docker",
        [
            ("info*", "ok", 0),
            ("network inspect proxy-egress*", "10.231.0.0/24", inspect_rc),
            ("network inspect demo-egress*", "10.233.0.0/24", inspect_rc),
        ],
    )
    stubs.add("ip", [("*route*", routes, 0)])


def _net_args(tmp_path: Path) -> list[str]:
    return ["--dry-run", "--bin-dir", str(tmp_path / "sbin"), "--unit-dir", str(tmp_path / "units")]


def test_proxy_net_dry_run_creates_both_networks_once(
    run_script: Runner, stubs: Stubs, tmp_path: Path
) -> None:
    _net_stubs(stubs, exists=False)
    res = run_script("setup-proxy-net.sh", *_net_args(tmp_path))
    assert res.rc == 0, res.err
    creates = [p for p in _plans(res.out) if p.startswith("docker network create")]
    assert creates == [
        "docker network create --driver bridge --subnet 10.231.0.0/24 proxy-egress",
        "docker network create --driver bridge --subnet 10.233.0.0/24 demo-egress",
    ]
    assert not any("--internal" in c for c in creates), (
        "demo-net is created --internal by the demo compose file"
    )
    joined = "\n".join(_plans(res.out))
    assert "pruefstand-firewall.sh" in joined
    assert "pruefstand-firewall.service" in joined
    assert "systemctl enable" in joined
    assert "pruefstand-firewall" in joined
    assert "-F" not in joined, "the network script itself flushes no chain"


def test_proxy_net_second_run_creates_nothing(
    run_script: Runner, stubs: Stubs, tmp_path: Path
) -> None:
    _net_stubs(stubs, exists=True)
    res = run_script("setup-proxy-net.sh", *_net_args(tmp_path))
    assert res.rc == 0, res.err
    assert not [p for p in _plans(res.out) if p.startswith("docker network create")]


def test_proxy_net_refuses_a_clashing_route(
    run_script: Runner, stubs: Stubs, tmp_path: Path
) -> None:
    _net_stubs(stubs, exists=False, routes=ROUTES + "\n10.231.0.0/16 via 192.168.1.9 dev ens3")
    res = run_script("setup-proxy-net.sh", *_net_args(tmp_path))
    assert res.rc == 3
    assert "10.231.0.0/24" in res.err
    assert "clash" in res.err


def test_proxy_net_refuses_an_existing_network_with_another_subnet(
    run_script: Runner, stubs: Stubs, tmp_path: Path
) -> None:
    _net_stubs(stubs, exists=True)
    stubs.add(
        "docker",
        [("info*", "ok", 0), ("network inspect proxy-egress*", "10.99.0.0/24", 0), ("*", "", 0)],
    )
    assert run_script("setup-proxy-net.sh", *_net_args(tmp_path)).rc == 3

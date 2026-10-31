"""T0.7 CPU tests: ``pruefstand-firewall.sh`` rules, order, atomicity and safety (stub iptables)."""

import os
import re

import pytest
from vm_testkit import Runner, Stubs
from vm_world import IPT_INPUT, IPT_USER

ACCEPT = "-s 10.231.0.0/24 -d 172.17.0.1 -p tcp --dport 11434 -j ACCEPT"
DROP = "-d 172.17.0.1 -p tcp --dport 11434 -j DROP"
EMPTY_USER = "-N DOCKER-USER\n-A DOCKER-USER -j RETURN"


def _iptables(stubs: Stubs, *, present: bool, user: str = IPT_USER, inp: str = IPT_INPUT) -> None:
    rc = 0 if present else 1
    stubs.add(
        "iptables",
        [
            ("*-C *", "", rc),
            ("*-L PRUEFSTAND-INPUT*", "", rc),
            ("*-S DOCKER-USER", user if present else EMPTY_USER, 0),
            ("*-S PRUEFSTAND-INPUT", inp if present else "", 0 if present else 1),
            ("*", "", 0),
        ],
    )


def _plans(out: str) -> list[str]:
    return [ln.removeprefix("PLAN ") for ln in out.splitlines() if ln.startswith("PLAN ")]


def _rules(plans: list[str], chain: str) -> list[str]:
    return [p for p in plans if re.search(rf"\s-[IA] {chain}\b", p)]


def _simulate_docker_user(plans: list[str]) -> list[str]:
    """Apply the planned -I / -D operations to an empty DOCKER-USER (plus the stock RETURN)."""
    chain = ["-j RETURN"]
    for p in plans:
        m = re.search(r"-I DOCKER-USER (\d+) (.*)$", p)
        if m:
            chain.insert(int(m.group(1)) - 1, m.group(2))
    return chain


def test_fresh_install_orders_accept_before_drop_and_never_deletes(
    run_script: Runner, stubs: Stubs
) -> None:
    _iptables(stubs, present=False)
    res = run_script("pruefstand-firewall.sh", "--dry-run")
    assert res.rc == 0, res.err
    plans = _plans(res.out)
    final = _simulate_docker_user(plans)
    assert final.index(ACCEPT) < final.index(DROP)
    assert not [p for p in plans if re.search(r"\s-(D|F|X)\b", p)], "nothing is deleted or flushed"
    first_drop = next(i for i, p in enumerate(plans) if p.endswith(DROP) and "DOCKER-USER" in p)
    first_accept = next(i for i, p in enumerate(plans) if p.endswith(ACCEPT) and "DOCKER-USER" in p)
    assert first_drop < first_accept, "the drop goes in first, so it is never absent"


def test_input_chain_is_swapped_atomically_with_restore(run_script: Runner, stubs: Stubs) -> None:
    _iptables(stubs, present=False)
    plans = _plans(run_script("pruefstand-firewall.sh", "--dry-run").out)
    restore = [p for p in plans if p.startswith("iptables-restore --noflush")]
    assert restore, "PRUEFSTAND-INPUT is written in one iptables-restore transaction"
    rules = _rules(plans, "PRUEFSTAND-INPUT")
    accept = next(i for i, r in enumerate(rules) if r.endswith(ACCEPT))
    drop = next(i for i, r in enumerate(rules) if r.endswith(DROP))
    assert accept < drop
    assert not [p for p in plans if re.search(r"iptables -w -F", p)]
    jump = next(i for i, p in enumerate(plans) if "-I INPUT" in p and "-j PRUEFSTAND-INPUT" in p)
    assert jump > max(i for i, p in enumerate(plans) if p.startswith("iptables-restore"))


def test_demo_rules_and_conntrack_return(run_script: Runner, stubs: Stubs) -> None:
    _iptables(stubs, present=False)
    plans = _plans(run_script("pruefstand-firewall.sh", "--dry-run").out)
    user = "\n".join(_rules(plans, "DOCKER-USER"))
    for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"):
        assert f"-s 10.233.0.0/24 -d {net} -j DROP" in user
    assert "10.232.0.0/24" not in user, "demo-net is --internal: no DOCKER-USER rule for it"
    assert "RETURN" not in user
    inp = _rules(plans, "PRUEFSTAND-INPUT")
    texts = [r.split("PRUEFSTAND-INPUT ", 1)[1] for r in inp if "-j PRUEFSTAND-INPUT" not in r]
    ret = texts.index("-m conntrack --ctstate ESTABLISHED,RELATED -j RETURN")
    assert ret < texts.index("-s 10.232.0.0/24 -j DROP") < texts.index("-s 10.233.0.0/24 -j DROP")


def test_second_run_changes_nothing(run_script: Runner, stubs: Stubs) -> None:
    _iptables(stubs, present=True)
    res = run_script("pruefstand-firewall.sh", "--dry-run")
    assert res.rc == 0
    assert _plans(res.out) == []
    assert "no changes" in res.out


def test_misordered_accept_is_fixed_without_removing_the_drop_first(
    run_script: Runner, stubs: Stubs
) -> None:
    lines = IPT_USER.splitlines()
    swapped = "\n".join([lines[0], lines[2], lines[1], *lines[3:]])
    _iptables(stubs, present=True, user=swapped)
    plans = _plans(run_script("pruefstand-firewall.sh", "--dry-run").out)
    insert = next(i for i, p in enumerate(plans) if "-I DOCKER-USER 1" in p and p.endswith(ACCEPT))
    delete = next(i for i, p in enumerate(plans) if re.search(r"-D DOCKER-USER \d+$", p))
    assert insert < delete
    assert not [p for p in plans if "-D" in p and "DROP" in p]


def test_check_mode_reports_missing_and_misordered(run_script: Runner, stubs: Stubs) -> None:
    _iptables(stubs, present=True)
    assert run_script("pruefstand-firewall.sh", "--check").rc == 0
    _iptables(stubs, present=False)
    res = run_script("pruefstand-firewall.sh", "--check")
    assert res.rc == 1
    assert "missing" in res.out
    lines = IPT_INPUT.splitlines()
    swapped = "\n".join([lines[0], lines[2], lines[1], *lines[3:]])
    _iptables(stubs, present=True, inp=swapped)
    res = run_script("pruefstand-firewall.sh", "--check")
    assert res.rc == 1
    assert "order" in res.out


def test_aborts_when_a_non_docker_route_overlaps_the_demo_networks(
    run_script: Runner, stubs: Stubs
) -> None:
    _iptables(stubs, present=False)
    stubs.add(
        "ip",
        [
            (
                "*route*",
                "default via 192.168.1.1 dev ens3\n10.233.0.0/16 via 192.168.1.9 dev ens3",
                0,
            )
        ],
    )
    res = run_script("pruefstand-firewall.sh", "--dry-run")
    assert res.rc == 3
    assert "10.233.0.0/24" in res.err
    assert "SSH" in res.err
    stubs.add(
        "ip",
        [("*route*", "default via 192.168.1.1 dev ens3\n10.233.0.0/24 dev br-1a2b scope link", 0)],
    )
    assert run_script("pruefstand-firewall.sh", "--dry-run").rc == 0


def test_real_run_needs_root(run_script: Runner, stubs: Stubs) -> None:
    if os.geteuid() == 0:
        pytest.skip("running as root: the refusal cannot be observed")
    _iptables(stubs, present=False)
    assert run_script("pruefstand-firewall.sh").rc == 2
    assert all("-I" not in c and "-A" not in c for c in stubs.calls("iptables"))
    assert not stubs.calls("iptables-restore")

"""T0.7 CPU tests: ``setup-proxy-net.sh`` (D242, N4.2, P2.2)."""

from pathlib import Path

from vm_testkit import Runner, Stubs

ROUTES = "default via 192.168.1.1 dev ens3\n172.17.0.0/16 dev docker0\n192.168.1.0/24 dev ens3"


def _plans(out: str) -> list[str]:
    return [ln.removeprefix("PLAN ") for ln in out.splitlines() if ln.startswith("PLAN ")]


# --- setup-proxy-net.sh ---------------------------------------------------------------
def _net_stubs(stubs: Stubs, *, exists: bool, routes: str = ROUTES) -> None:
    inspect_rc = 0 if exists else 1
    stubs.add(
        "docker",
        [
            ("info*", "ok", 0),
            ("network inspect proxy-egress*bridge.name*", "pfproxy0", inspect_rc),
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
        "docker network create --driver bridge --subnet 10.231.0.0/24 "
        "-o com.docker.network.bridge.name=pfproxy0 proxy-egress",
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


def test_proxy_net_also_guards_the_demo_net_subnet(
    run_script: Runner, stubs: Stubs, tmp_path: Path
) -> None:
    _net_stubs(stubs, exists=True, routes=ROUTES + "\n10.232.0.0/16 via 192.168.1.9 dev ens3")
    res = run_script("setup-proxy-net.sh", *_net_args(tmp_path))
    assert res.rc == 3
    assert "10.232.0.0/24" in res.err


def test_proxy_net_ignores_docker_bridges_and_handles_blackhole_routes(
    run_script: Runner, stubs: Stubs, tmp_path: Path
) -> None:
    routes = ROUTES + "\n10.232.0.0/24 dev br-abc scope link\nblackhole 203.0.113.0/24"
    _net_stubs(stubs, exists=False, routes=routes)
    res = run_script("setup-proxy-net.sh", *_net_args(tmp_path))
    assert res.rc == 0, res.err


def test_proxy_net_plans_no_ownership_flags_it_cannot_set(
    run_script: Runner, stubs: Stubs, tmp_path: Path
) -> None:
    _net_stubs(stubs, exists=True)
    assert (
        "pruefstand-firewall.service" in run_script("setup-proxy-net.sh", *_net_args(tmp_path)).out
    )


def test_proxy_net_refuses_an_existing_network_without_the_fixed_bridge(
    run_script: Runner, stubs: Stubs, tmp_path: Path
) -> None:
    _net_stubs(stubs, exists=True)
    stubs.add(
        "docker",
        [
            ("info*", "ok", 0),
            ("network inspect proxy-egress*bridge.name*", "br-abc123", 0),
            ("network inspect*", "10.231.0.0/24", 0),
        ],
    )
    res = run_script("setup-proxy-net.sh", *_net_args(tmp_path))
    assert res.rc == 3
    assert "pfproxy0" in res.err

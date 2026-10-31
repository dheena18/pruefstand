"""T0.7 CPU tests: the systemd units and ``install-tunnel.sh``."""

import re
from pathlib import Path

from vm_testkit import VM_DIR, Runner

TUNNEL = (VM_DIR / "pruefstand-tunnel.service").read_text(encoding="utf-8")
FIREWALL = (VM_DIR / "pruefstand-firewall.service").read_text(encoding="utf-8")


def _section(text: str, name: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    current = ""
    for line in text.splitlines():
        if line.startswith("["):
            current = line.strip("[]")
        elif "=" in line and current == name:
            key, _, value = line.partition("=")
            out.setdefault(key, []).append(value)
    return out


def test_tunnel_is_a_system_unit_of_pruefstand_with_restart() -> None:
    service = _section(TUNNEL, "Service")
    assert service["User"] == ["pruefstand"]
    assert service["Group"] == ["pruefstand"]
    assert service["Restart"] == ["always"]
    assert service["RestartSec"] == ["10"]
    assert "AUTOSSH_GATETIME=0" in service["Environment"]
    unit = _section(TUNNEL, "Unit")
    assert "network-online.target" in unit["After"][0]
    assert "docker.service" in unit["After"][0]
    assert "network-online.target" in unit["Wants"][0]
    assert "docker.service" in unit["Wants"][0]
    assert _section(TUNNEL, "Install")["WantedBy"] == ["multi-user.target"]


def test_tunnel_forwards_only_11434_on_loopback_and_docker_gateway() -> None:
    exec_start = _section(TUNNEL, "Service")["ExecStart"][0]
    assert exec_start.startswith("/usr/bin/autossh -M 0 -N")
    assert "ExitOnForwardFailure=yes" in exec_start
    assert exec_start.endswith(" cairo-s101lp")
    forwards = re.findall(r"-L (\S+)", exec_start)
    assert sorted(forwards) == [
        "127.0.0.1:11434:localhost:11434",
        "172.17.0.1:11434:localhost:11434",
    ]
    assert "0." + "0.0.0" not in TUNNEL
    assert "*:" not in TUNNEL
    assert "sshpass" not in TUNNEL
    assert "PasswordAuthentication=yes" not in TUNNEL


def test_tunnel_has_no_mount_dependency() -> None:
    for key in ("Requires", "Wants", "After", "RequiresMountsFor", "BindsTo", "Before"):
        for section in ("Unit", "Service"):
            for value in _section(TUNNEL, section).get(key, []):
                assert "mnt-" not in value, (key, value)
                assert ".mount" not in value, (key, value)
                assert ".automount" not in value, (key, value)
    assert "mnt-" not in TUNNEL
    assert "RequiresMountsFor" not in TUNNEL


def test_firewall_unit_is_oneshot_tied_to_docker() -> None:
    service = _section(FIREWALL, "Service")
    assert service["Type"] == ["oneshot"]
    assert service["RemainAfterExit"] == ["yes"]
    assert service["ExecStart"] == ["/usr/local/sbin/pruefstand-firewall.sh"]
    unit = _section(FIREWALL, "Unit")
    assert unit["After"] == ["docker.service"]
    assert unit["PartOf"] == ["docker.service"]
    assert _section(FIREWALL, "Install")["WantedBy"] == ["docker.service"]


def test_install_tunnel_dry_run_plans_install_reload_enable_restart(
    run_script: Runner, tmp_path: Path
) -> None:
    unit_dir = tmp_path / "units"
    res = run_script("install-tunnel.sh", "--dry-run", "--unit-dir", unit_dir)
    assert res.rc == 0, res.err
    lines = [ln for ln in res.out.splitlines() if ln.startswith("PLAN")]
    joined = "\n".join(lines)
    assert f"{unit_dir}/pruefstand-tunnel.service" in joined
    order = [
        joined.index(k)
        for k in ("install ", "systemctl daemon-reload", "systemctl enable", "systemctl restart")
    ]
    assert order == sorted(order)
    assert "--user" not in res.out
    assert not unit_dir.exists()


def test_install_tunnel_second_run_with_same_unit_only_enables(
    run_script: Runner, tmp_path: Path
) -> None:
    unit_dir = tmp_path / "units"
    unit_dir.mkdir()
    (unit_dir / "pruefstand-tunnel.service").write_text(TUNNEL, encoding="utf-8")
    res = run_script("install-tunnel.sh", "--dry-run", "--unit-dir", unit_dir)
    assert "install " not in res.out
    assert "systemctl restart" not in res.out
    assert "systemctl enable --now pruefstand-tunnel" in res.out


def test_tunnel_fails_closed_without_the_firewall() -> None:
    unit = _section(TUNNEL, "Unit")
    assert "pruefstand-firewall.service" in unit["After"][0]
    assert unit["Requires"] == ["pruefstand-firewall.service"]
    pre = _section(TUNNEL, "Service")["ExecStartPre"]
    assert pre == ["+/usr/local/sbin/pruefstand-firewall.sh --check-gateway"]


def test_tunnel_notices_dead_connections() -> None:
    exec_start = _section(TUNNEL, "Service")["ExecStart"][0]
    assert "-o ServerAliveInterval=30" in exec_start
    assert "-o ServerAliveCountMax=3" in exec_start


def test_tunnel_is_hardened_without_breaking_autossh() -> None:
    service = _section(TUNNEL, "Service")
    assert service["NoNewPrivileges"] == ["yes"]
    assert service["PrivateTmp"] == ["yes"]
    assert service["ProtectSystem"] == ["full"]


def test_firewall_unit_retries_on_failure() -> None:
    service = _section(FIREWALL, "Service")
    assert service["Restart"] == ["on-failure"]
    assert service["RestartSec"] == ["5"]

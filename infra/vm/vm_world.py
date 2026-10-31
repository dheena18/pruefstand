"""A healthy fake VM for the ``vm_check.sh`` tests: files, env and stub rules (T0.7).

Tests start from :func:`build_world` (every check PASSes) and override single stub rules.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from vm_testkit import VM_DIR, Result, Rule, Runner, Stubs

PF = "pruefstand:pruefstand"
UNIT = (VM_DIR / "pruefstand-tunnel.service").read_text(encoding="utf-8")
IPT_USER = """-P DOCKER-USER ACCEPT
-A DOCKER-USER -s 10.231.0.0/24 -d 172.17.0.1/32 -p tcp -m tcp --dport 11434 -j ACCEPT
-A DOCKER-USER -d 172.17.0.1/32 -p tcp -m tcp --dport 11434 -j DROP
-A DOCKER-USER -s 10.233.0.0/24 -d 10.0.0.0/8 -j DROP
-A DOCKER-USER -s 10.233.0.0/24 -d 172.16.0.0/12 -j DROP
-A DOCKER-USER -s 10.233.0.0/24 -d 192.168.0.0/16 -j DROP
-A DOCKER-USER -j RETURN"""
IPT_INPUT = """-N PRUEFSTAND-INPUT
-A PRUEFSTAND-INPUT -s 10.231.0.0/24 -d 172.17.0.1/32 -p tcp -m tcp --dport 11434 -j ACCEPT
-A PRUEFSTAND-INPUT -d 172.17.0.1/32 -p tcp -m tcp --dport 11434 -j DROP
-A PRUEFSTAND-INPUT -m conntrack --ctstate RELATED,ESTABLISHED -j RETURN
-A PRUEFSTAND-INPUT -s 10.232.0.0/24 -j DROP
-A PRUEFSTAND-INPUT -s 10.233.0.0/24 -j DROP"""
LISTEN = (
    'LISTEN 0 128 127.0.0.1:11434 0.0.0.0:* users:(("ssh",pid=11,fd=5))\n'
    'LISTEN 0 128 172.17.0.1:11434 0.0.0.0:* users:(("ssh",pid=11,fd=6))\n'
    "LISTEN 0 128 0.0.0.0:22 0.0.0.0:*"
)


@dataclass
class World:
    """A healthy fake VM; tests override single stub rules."""

    root: Path
    stubs: Stubs
    env: dict[str, str]
    rules: dict[str, list[Rule]] = field(default_factory=dict)

    def put(self, name: str, rules: list[Rule]) -> None:
        """Install (or replace) the stub ``name`` with ``rules``."""
        self.rules[name] = rules
        self.stubs.add(name, rules)

    def override(self, name: str, *first: Rule) -> None:
        """Prepend rules (first match wins) to the stub ``name``."""
        self.put(name, [*first, *self.rules[name]])


def _files(tmp_path: Path) -> tuple[dict[str, str], Path]:
    """Write the fake files; return the env for ``vm_check.sh`` and the owner's home."""
    data, lock, ownerhome = tmp_path / "data", tmp_path / "lock", tmp_path / "ownerhome"
    (data / "cache").mkdir(parents=True)
    (data / ".pruefstand-data-root").touch()
    lock.mkdir()
    (lock / "gpu.lock").touch()
    (ownerhome / ".ssh").mkdir(parents=True)
    (tmp_path / "os-release").write_text('ID=ubuntu\nVERSION_ID="24.04"\n', encoding="utf-8")
    (tmp_path / "meminfo").write_text("MemTotal:       65900000 kB\n", encoding="utf-8")
    (tmp_path / "fstab").write_text("UUID=abc / ext4 defaults 0 1\n", encoding="utf-8")
    (tmp_path / "env").write_text(
        "OLLAMA_GPU0_URL=http://127.0.0.1:11434\nOLLAMA_GPU1_URL=http://127.0.0.1:11434\n",
        encoding="utf-8",
    )
    env = {
        "OS_RELEASE_FILE": str(tmp_path / "os-release"), "MEMINFO_FILE": str(tmp_path / "meminfo"),
        "FSTAB_FILE": str(tmp_path / "fstab"), "PRUEFSTAND_ENV_FILE": str(tmp_path / "env"),
        "PRUEFSTAND_LOCK_DIR": str(lock),
        "PRUEFSTAND_DATA_ROOT": str(data),
        "TRUENAS_HOST_IP": "10.0.0.2",
        "PROBE_IMAGE": "curlimages/curl@sha256:" + "ab" * 32,
        "PRUEFSTAND_ALLOW_ROOT": "1",
        "PRUEFSTAND_CONFIRM_FILE": str(tmp_path / "confirmed"),
        "DRILL_WAIT_S": "0",
        "HOME": str(tmp_path / "h"),
    }  # fmt: skip
    return env, ownerhome


def _host_stubs(world: World, ownerhome: Path) -> None:
    stubs = world.stubs
    stubs.add_sudo()
    stubs.link("pruefstand-lock", VM_DIR / "pruefstand-lock")
    big = "Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/x 900000000 1 {} 1% /"
    world.put("df", [("*-Pk /", big.format(400_000_000), 0), ("*", big.format(300_000_000), 0)])
    world.put("nproc", [("*", "8", 0)])
    world.put("hostname", [("*", "192.168.1.50 172.17.0.1", 0)])
    world.put("findmnt", [("*", "/", 0)])
    world.put(
        "stat",
        [("*gpu.lock", f"660 {PF}", 0), ("*%G *lock", f"2770 {PF}", 0), ("*%U *", "pruefstand", 0)],
    )
    world.put(
        "getent",
        [
            ("passwd pruefstand", "pruefstand:x:998:998::/home/pruefstand:/bin/bash", 0),
            ("passwd alice", f"alice:x:1000:1000::{ownerhome}:/bin/bash", 0),
            ("ahostsv4 cluster.invalid", "192.168.77.5 STREAM cluster.invalid", 0),
            ("group docker", "docker:x:999:alice,pruefstand", 0),
            ("group pruefstand", "pruefstand:x:998:alice", 0),
        ],
    )
    world.put(
        "ip",
        [
            (
                "-4 addr show docker0",
                "    inet 172.17.0.1/16 brd 172.17.255.255 scope global docker0",
                0,
            )
        ],
    )
    world.put("ss", [("*", LISTEN, 0)])
    world.put("curl", [("*127.0.0.1:11434/api/tags*", "200", 0)])


def _service_stubs(world: World) -> None:
    world.put(
        "systemctl",
        [
            ("is-active pruefstand-firewall", "active", 0),
            ("is-active pruefstand-tunnel", "active", 0),
            ("is-enabled nftables", "disabled", 1),
            ("show -p User --value pruefstand-tunnel", "pruefstand", 0),
            (
                "show -p FragmentPath --value pruefstand-tunnel",
                "/etc/systemd/system/pruefstand-tunnel.service",
                0,
            ),
            ("cat pruefstand-tunnel", UNIT, 0),
            ("restart docker", "", 0),
            ("show -p ActiveEnterTimestampMonotonic --value pruefstand-firewall", "{n}00", 0),
        ],
    )
    world.put(
        "iptables",
        [
            ("*-C INPUT*", "", 0),
            ("*-S DOCKER-USER", IPT_USER, 0), ("*-S PRUEFSTAND-INPUT", IPT_INPUT, 0),
            ("*-S DOCKER-ISOLATION-STAGE-1", "-N DOCKER-ISOLATION-STAGE-1", 0),
            ("*-t nat -S DOCKER", "-N DOCKER", 0),
        ],
    )  # fmt: skip


def _docker_stubs(world: World) -> None:
    world.put(
        "docker",
        [
            ("info -f*", "[name=apparmor name=seccomp,profile=builtin name=cgroupns]", 0),
            ("info*", "ok", 0),
            ("ps -q*", "", 0),
            ("network inspect proxy-egress*", "10.231.0.0/24 false", 0),
            ("network inspect demo-egress*", "10.233.0.0/24", 0),
            ("network inspect*", "", 1),
            ("network create*", "id", 0),
            ("network rm*", "", 0),
            ("network connect*", "", 0),
            ("rm -f*", "", 0),
            ("run -d*", "cid", 0),
            ("exec*example.com*", "200", 0), ("exec*", "000", 28),
            ("run*--network proxy-egress*", "200", 0),
            ("run*--network bridge*", "000", 28),
            ("run*", "000", 28),
        ],
    )  # fmt: skip
    world.put(
        "gh",
        [
            ("auth token", "github_pat_TESTONLY", 0),
            ("api repos/dheena18/pruefstand --jq .permissions.admin", "false", 0),
            ("api repos/dheena18/pruefstand-gate*", "", 1, "gh: Not Found (HTTP 404)"),
        ],
    )
    world.put(
        "ssh",
        [
            ("*-G cairo-s101lp", "hostname cluster.invalid\nport 4711", 0),
            ("*BatchMode=yes*cairo-s101lp true", "", 0),
        ],
    )


def build_world(tmp_path: Path, stubs: Stubs) -> World:
    """Return a fake VM on which every ``vm_check.sh`` check passes."""
    env, ownerhome = _files(tmp_path)
    world = World(tmp_path, stubs, env)
    _host_stubs(world, ownerhome)
    _service_stubs(world)
    _docker_stubs(world)
    return world


def check(
    world: World, run_script: Runner, *args: str, env: dict[str, str] | None = None
) -> dict[str, tuple[str, str]]:
    """Run vm_check.sh and return ``{id: (status, detail)}``."""
    res = raw(world, run_script, *args, env=env)
    rows = {}
    for line in res.out.splitlines():
        m = re.fullmatch(r"CHECK (\S+) (PASS|FAIL|WARN) (.*)", line)
        if m is None:
            message = f"bad line: {line!r}\nstderr: {res.err}"
            raise AssertionError(message)
        rows[m.group(1)] = (m.group(2), m.group(3))
    return rows


def raw(world: World, run_script: Runner, *args: str, env: dict[str, str] | None = None) -> Result:
    """Run vm_check.sh as owner ``alice`` on the fake VM and return the raw result."""
    return run_script("vm_check.sh", "--owner", "alice", *args, env={**world.env, **(env or {})})

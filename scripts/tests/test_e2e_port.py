"""The Try-it e2e port must be in no other row of the port map (found by the T5.4e pilot)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / "scripts" / "demo" / "try_e2e.sh").read_text(encoding="utf-8")
DOCKER_MD = (ROOT / "docs" / "engineering" / "docker.md").read_text(encoding="utf-8")
ENV_EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf-8")
PORT = re.compile(r"(?<![\w.])(\d{4,5})(?![\w.])")


def _base() -> int:
    match = re.search(r'E2E_PORT="\$\{E2E_PORT:-\$\(\((\d+) \+ \$\{PORT_OFFSET:-0\}\)\)\}"', SCRIPT)
    assert match, "the E2E_PORT default of try_e2e.sh changed shape"
    return int(match.group(1))


def _reserved() -> set[int]:
    """Every port the port map (docker.md section 3, minus the e2e row) and .env.example name."""
    rows = [
        line
        for line in DOCKER_MD.splitlines()
        if line.startswith("|") and "rag-demo-e2e" not in line
    ]
    reserved = {int(p) for line in rows for p in PORT.findall(line)}
    env_ports = re.findall(
        r"^#?\s*[A-Z0-9_]*PORT[A-Z0-9_]*=(\d{4,5})\s*(?:#.*)?$", ENV_EXAMPLE, re.M
    )
    reserved |= {int(p) for p in env_ports}
    reserved |= {int(p) + 10000 for p in map(int, env_ports) if p < 10000}
    return reserved


def test_the_e2e_port_is_in_no_other_row_of_the_port_map() -> None:
    reserved = _reserved()
    assert {18091, 18080, 18090, 18000, 18201, 6333, 8000}.issubset(
        reserved
    )  # the parser sees the map
    for offset in (0, 10000):
        assert _base() + offset not in reserved, (
            f"E2E_PORT {_base() + offset} clashes with the port map"
        )


def test_the_port_map_lists_the_e2e_instance_with_its_real_ports() -> None:
    row = next(
        line for line in DOCKER_MD.splitlines() if line.startswith("|") and "rag-demo-e2e" in line
    )
    assert str(_base()) in row
    assert str(_base() + 10000) in row

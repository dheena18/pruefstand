import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MAKE = shutil.which("make") or "make"


def _make(
    *args: str,
    offset: str | None = "0",
    env_file: Path | None = None,
    project: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in {"PORT_OFFSET", "COMPOSE_PROJECT_NAME"}}
    if offset is not None:
        env["PORT_OFFSET"] = offset
    if project is not None:
        env["COMPOSE_PROJECT_NAME"] = project
    extra = [f"ENV_FILE={env_file}"] if env_file else []
    return subprocess.run(  # noqa: S603
        [MAKE, "-C", str(REPO), *extra, *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _ports(offset: str) -> dict[str, int]:
    out = _make("-s", "ports", offset=offset).stdout.split()
    return {name: int(port) for name, port in zip(out[::2], out[1::2], strict=True)}


def test_ports_defaults_with_zero_offset() -> None:
    assert _ports("0") == {
        "qdrant": 6333,
        "qdrant-grpc": 6334,
        "llm": 8080,
        "embed": 8090,
        "rag-demo": 8000,
        "rerank-cpu": 8201,
        "llm-proxy": 11500,
    }


def test_ports_add_the_offset() -> None:
    ports = _ports("10000")
    assert ports["qdrant"] == 16333
    assert ports["rag-demo"] == 18000
    assert ports["rerank-cpu"] == 18201
    assert ports["llm-proxy"] == 21500


def test_up_command_line() -> None:
    result = _make(
        "-n",
        "up",
        "PROFILES=live dev",
        "SERVICES=llm",
        "WAIT=1",
        "COMPOSE_FILES=x.yml",
    )
    assert (
        "docker compose -f docker-compose.yml -f x.yml --profile live --profile dev "
        "up -d --wait llm" in result.stdout
    )


def test_down_keeps_volumes_unless_asked() -> None:
    assert " -v" not in _make("-n", "down").stdout
    assert "--remove-orphans -v" in _make("-n", "down", "VOLUMES=1").stdout


def test_smoke_tag_is_overridable() -> None:
    assert "-t pruefstand-smoke ." in _make("-n", "image-smoke").stdout
    assert "-t smoke-wt1 ." in _make("-n", "image-smoke", "SMOKE_TAG=smoke-wt1").stdout


@pytest.mark.parametrize(
    "bad", ["007", "-1", "1 2", "1e3", "54036", "99999999999999999999", "1;id"]
)
def test_invalid_offsets_are_rejected(bad: str) -> None:
    result = _make("-s", "ports", offset=bad)
    assert result.returncode != 0
    assert "PORT_OFFSET" in result.stderr


def test_largest_valid_offset_keeps_ports_in_range() -> None:
    assert _ports("54035")["llm-proxy"] == 65535


def test_project_defaults_to_the_shared_dev_project_with_an_offset() -> None:
    assert _make("-s", "project", offset="10000").stdout.strip() == "pruefstand-dev"
    assert _make("-s", "project", offset="0").stdout.strip() == ""


def test_explicit_project_wins(tmp_path: Path) -> None:
    assert _make("-s", "project", offset="10000", project="mine").stdout.strip() == "mine"
    env_file = tmp_path / "env"
    env_file.write_text("COMPOSE_PROJECT_NAME=from-file\n", encoding="utf-8")
    out = _make("-s", "project", offset="10000", env_file=env_file).stdout
    assert out.strip() == "from-file"


def test_ports_env_writes_one_idempotent_block(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=bar\nPORT_OFFSET=0\n\n# note\nBAZ=qux", encoding="utf-8")
    for _ in range(2):
        assert _make("ports-env", offset="10000", env_file=env_file).returncode == 0
    text = env_file.read_text(encoding="utf-8")
    assert text.count("# >>> ports (make ports-env)") == 1
    assert text.count("# <<< ports") == 1
    assert "QDRANT_HTTP_PORT=16333\n" in text
    assert text.startswith("FOO=bar\nPORT_OFFSET=0\n\n# note\nBAZ=qux\n")


def test_offset_is_read_from_the_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / "env"
    env_file.write_text("PORT_OFFSET=10000\n", encoding="utf-8")
    out = _make("-s", "ports", offset=None, env_file=env_file).stdout
    assert "qdrant 16333" in out


def test_check_ports_warns_with_the_project_and_fails_when_strict() -> None:
    stub = "printf 'wt1 wt1-qdrant-1 127.0.0.1:6333->6333/tcp, 127.0.0.1:16334->6334/tcp\\n'"
    warn = _make("check-ports", f"CHECK_PORTS_PS={stub}")
    assert warn.returncode == 0
    assert "project wt1" in warn.stderr
    assert "6333" in warn.stderr
    assert "16334" not in warn.stderr
    assert _make("check-ports", "STRICT=1", f"CHECK_PORTS_PS={stub}").returncode != 0


def test_check_ports_ignores_the_executor_project() -> None:
    stub = "printf 'pruefstand-exec pruefstand-exec-qdrant-1 127.0.0.1:6333->6333/tcp\\n'"
    result = _make("check-ports", "STRICT=1", f"CHECK_PORTS_PS={stub}")
    assert result.returncode == 0
    assert result.stderr == ""


def test_check_ports_is_quiet_for_dev_ports() -> None:
    stub = "printf 'pruefstand-dev pruefstand-dev-qdrant-1 127.0.0.1:16333->6333/tcp\\n'"
    result = _make("check-ports", "STRICT=1", f"CHECK_PORTS_PS={stub}")
    assert result.returncode == 0
    assert result.stderr == ""


def test_environment_port_offset_is_not_expanded_by_make(tmp_path: Path) -> None:
    marker = tmp_path / "pwned"
    result = _make("-s", "ports", offset=f"$(shell touch {marker})")
    assert result.returncode != 0
    assert "PORT_OFFSET" in result.stderr
    assert not marker.exists()


def test_environment_project_name_is_not_expanded_by_make(tmp_path: Path) -> None:
    marker = tmp_path / "pwned2"
    out = _make("-s", "project", offset="10000", project=f"$(shell touch {marker})").stdout
    assert not marker.exists()
    assert "touch" in out


def test_check_ports_expands_ranges_and_reports_each_port_once() -> None:
    stub = (
        "printf 'wt1 wt1-qdrant-1 0.0.0.0:6333-6334->6333-6334/tcp, "
        "[::]:6333-6334->6333-6334/tcp\\n'"
    )
    result = _make("check-ports", f"CHECK_PORTS_PS={stub}")
    assert result.stderr.count("default port 6333") == 1
    assert result.stderr.count("default port 6334") == 1


def test_check_ports_range_without_default_ports_is_quiet() -> None:
    stub = "printf 'wt1 wt1-x-1 127.0.0.1:16000-16010->6000-6010/tcp\\n'"
    assert _make("check-ports", f"CHECK_PORTS_PS={stub}").stderr == ""


def test_ports_env_adds_the_shared_project_once_with_an_offset(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=bar\n", encoding="utf-8")
    for _ in range(2):
        assert _make("ports-env", offset="10000", env_file=env_file).returncode == 0
    text = env_file.read_text(encoding="utf-8")
    assert text.count("COMPOSE_PROJECT_NAME=pruefstand-dev\n") == 1


def test_ports_env_keeps_an_existing_project_name(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("COMPOSE_PROJECT_NAME=mine\n", encoding="utf-8")
    assert _make("ports-env", offset="10000", env_file=env_file).returncode == 0
    text = env_file.read_text(encoding="utf-8")
    assert text.count("COMPOSE_PROJECT_NAME") == 1


def test_ports_env_without_an_offset_adds_no_project_name(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=bar\n", encoding="utf-8")
    assert _make("ports-env", offset="0", env_file=env_file).returncode == 0
    assert "COMPOSE_PROJECT_NAME" not in env_file.read_text(encoding="utf-8")

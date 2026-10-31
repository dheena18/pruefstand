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


def test_stack_run_holds_one_lock_with_a_teardown_trap(tmp_path: Path) -> None:
    lock = f"STACK_LOCK={tmp_path}/stack.lock"
    line = next(
        ln for ln in _make("-n", "stack-run", "CMD=true", lock).stdout.splitlines() if "flock" in ln
    )
    assert "stack.lock" in line
    assert 'make --no-print-directory down" EXIT' in line
    assert line.index("up WAIT=1") < line.index("true")


@pytest.mark.skipif(shutil.which("flock") is None, reason="needs flock")
@pytest.mark.parametrize("code", [0, 3])
def test_stack_run_tears_down_and_keeps_the_exit_code(tmp_path: Path, code: int) -> None:
    result = _make(
        "stack-run",
        f"CMD=echo checks; exit {code}",
        f"STACK_LOCK={tmp_path}/stack.lock",
        "COMPOSE_BASE=echo compose",
    )
    # make itself exits 2 when a recipe fails and reports the recipe's status ("Error 3")
    assert (result.returncode == 0) if code == 0 else f"Error {code}" in result.stderr
    lines = result.stdout.splitlines()
    assert any("up -d --wait" in ln for ln in lines)
    assert "checks" in lines
    assert any("down --remove-orphans" in ln for ln in lines)
    assert max(i for i, ln in enumerate(lines) if "down" in ln) > lines.index("checks")


@pytest.mark.skipif(shutil.which("flock") is None, reason="needs flock")
def test_stack_run_tears_down_when_up_fails(tmp_path: Path) -> None:
    result = _make(
        "stack-run",
        "CMD=echo checks",
        f"STACK_LOCK={tmp_path}/stack.lock",
        "COMPOSE_BASE=false",
    )
    assert result.returncode != 0
    assert "checks" not in result.stdout.splitlines()


def test_stack_run_lock_wait_is_optional() -> None:
    plain = _make("-n", "stack-run", "CMD=true").stdout
    waiting = _make("-n", "stack-run", "CMD=true", "STACK_LOCK_WAIT=30").stdout
    assert "flock -w 30 " in waiting
    assert "flock -w" not in plain


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

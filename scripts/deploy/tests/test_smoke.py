"""infra/deploy/smoke.sh with a fake curl that plays the demo (the DOCKER bats run is separate)."""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "infra" / "deploy" / "smoke.sh"
FAKE_CURL = """#!/bin/sh
case "$*" in
  *"/v1/health"*) printf '%s' "$FAKE_HEALTH" ;;
  *no_such_tenant*) printf '%s\\n%s' "$FAKE_ERROR_BODY" "$FAKE_ERROR_CODE" ;;
  *) printf '%s\\n%s' "$FAKE_QUERY_BODY" "$FAKE_QUERY_CODE" ;;
esac
"""
GOOD = {
    "FAKE_HEALTH": '{"status": "ok", "stats": {}}',
    "FAKE_QUERY_BODY": '{"answer": "x", "citations": ["§ 622 BGB"], "chunks": []}',
    "FAKE_QUERY_CODE": "200",
    "FAKE_ERROR_BODY": '{"code": "invalid_request", "message": "m", "retry_after_s": null}',
    "FAKE_ERROR_CODE": "422",
}

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="needs jq")


def _run(
    tmp_path: Path, url: str = "https://demo.example.org", **env: str
) -> subprocess.CompletedProcess[str]:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    curl = bindir / "curl"
    curl.write_text(FAKE_CURL, encoding="utf-8")
    curl.chmod(curl.stat().st_mode | stat.S_IXUSR)
    full = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", **GOOD, **env}
    return subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), url],  # noqa: S607
        env=full, capture_output=True, text=True, timeout=30, check=False,
    )  # fmt: skip


def test_a_healthy_demo_passes(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "1 citation(s)" in result.stdout
    assert "all checks passed" in result.stdout


@pytest.mark.parametrize(
    ("env", "needle"),
    [
        ({"FAKE_HEALTH": '{"status": "degraded"}'}, "health: status is not ok"),
        ({"FAKE_QUERY_CODE": "503"}, "query: HTTP 503"),
        ({"FAKE_QUERY_BODY": '{"answer": "x", "citations": []}'}, "no citation"),
        ({"FAKE_ERROR_CODE": "200"}, "expected an error"),
        ({"FAKE_ERROR_BODY": "<html>502</html>"}, "no code invalid_request"),
        ({"FAKE_ERROR_BODY": '{"code": "server_error"}'}, "no code invalid_request"),
    ],
)
def test_each_check_fails_on_its_own(tmp_path: Path, env: dict[str, str], needle: str) -> None:
    result = _run(tmp_path, **env)
    assert result.returncode == 1
    assert needle in result.stderr


def test_usage_errors_exit_two(tmp_path: Path) -> None:
    result = _run(tmp_path, url="demo.example.org")
    assert result.returncode == 2
    assert "must start with http" in result.stderr

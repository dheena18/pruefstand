"""scripts/deploy/build_dashboard.sh with a fake pnpm: build env, BUILD.json, refusals."""

import json
import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "deploy" / "build_dashboard.sh"
SHA = "a" * 40
FAKE_PNPM = """#!/bin/sh
env | grep -E '^(DASHBOARD_DATA_DIR|NEXT_BASE_PATH|NEXT_PUBLIC_DEMO_API_URL)=' |\\
  sort > "$FAKE_ENV_LOG"
printf '%s\\n' "$*" >> "$FAKE_ENV_LOG"
[ -n "$FAKE_PNPM_FAIL" ] && exit 1
mkdir -p out && echo '<html></html>' > out/index.html
"""


def _run(
    tmp_path: Path, *, data: Path | None = None, **env: str
) -> subprocess.CompletedProcess[str]:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    pnpm = bindir / "pnpm"
    pnpm.write_text(FAKE_PNPM, encoding="utf-8")
    pnpm.chmod(pnpm.stat().st_mode | stat.S_IXUSR)
    app = tmp_path / "app"
    app.mkdir(exist_ok=True)
    if data is None:
        data = tmp_path / "data"
        data.mkdir(exist_ok=True)
        (data / "manifest.json").write_text("{}", encoding="utf-8")
    full = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "FAKE_ENV_LOG": str(tmp_path / "env.log"),
        "DASHBOARD_APP_DIR": str(app),
        "DATA_SHA": SHA,
        "DEPLOY_RUN_ID": "4242",
        "GIT_SHA": "b" * 40,
        **env,
    }
    return subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), str(data)],  # noqa: S607
        env=full, capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip


def test_the_build_gets_the_tree_the_base_path_and_the_demo_url(tmp_path: Path) -> None:
    result = _run(tmp_path, NEXT_PUBLIC_DEMO_API_URL="https://demo.example.org")
    assert result.returncode == 0, result.stderr
    log = (tmp_path / "env.log").read_text(encoding="utf-8")
    assert f"DASHBOARD_DATA_DIR={tmp_path / 'data'}" in log
    assert "NEXT_BASE_PATH=/pruefstand" in log
    assert "NEXT_PUBLIC_DEMO_API_URL=https://demo.example.org" in log
    assert log.rstrip().endswith("build")


def test_build_json_and_the_size_line(tmp_path: Path) -> None:
    result = _run(tmp_path)
    build = json.loads((tmp_path / "app" / "out" / "BUILD.json").read_text(encoding="utf-8"))
    assert build == {"data_sha": SHA, "deploy_run_id": 4242, "git_sha": "b" * 40}
    assert result.stdout.split()[0].isdigit()
    assert str(tmp_path / "app" / "out") in result.stdout
    assert "NEXT_PUBLIC_DEMO_API_URL=\n" in (tmp_path / "env.log").read_text(encoding="utf-8")


def test_a_failed_build_leaves_no_build_json_and_no_stale_out(tmp_path: Path) -> None:
    (tmp_path / "app" / "out").mkdir(parents=True)
    (tmp_path / "app" / "out" / "BUILD.json").write_text("stale")
    result = _run(tmp_path, FAKE_PNPM_FAIL="1")
    assert result.returncode != 0
    assert not (tmp_path / "app" / "out").exists()


def test_refusals_happen_before_any_build(tmp_path: Path) -> None:
    for result in (_run(tmp_path, DATA_SHA="main"), _run(tmp_path, DEPLOY_RUN_ID="run-1")):
        assert result.returncode == 2
        assert not (tmp_path / "env.log").exists()
    bare = tmp_path / "bare"
    bare.mkdir()
    result = _run(tmp_path, data=bare)
    assert result.returncode == 2
    assert "no manifest.json" in result.stderr
    assert not (tmp_path / "env.log").exists()

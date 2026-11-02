"""The CLI against two real rag-demo instances (needs ``scripts/live/two_targets.sh``)."""

import json
from pathlib import Path

import httpx
import pytest
from testsupport.pipeline_support import BUG_URL, GOOD_URL, MINI_CONFIG, ROOT
from typer.testing import CliRunner

from pruefstand.cli import app

pytestmark = pytest.mark.live


def _reachable(url: str) -> bool:
    try:
        return httpx.get(f"{url}/v1/health", timeout=3).is_success
    except httpx.HTTPError:
        return False


@pytest.fixture(autouse=True)
def _targets() -> None:
    for url in (GOOD_URL, BUG_URL):
        if not _reachable(url):
            pytest.skip(
                f"{url} is not reachable; start scripts/live/two_targets.sh tenant_filter_post_topk"
            )


def _config(tmp_path: Path, name: str, url: str) -> Path:
    text = MINI_CONFIG.read_text(encoding="utf-8")
    text = text.replace("http://localhost:8000", url).replace(
        "datasets/fixtures/mini_v0", str(ROOT / "datasets/fixtures/mini_v0")
    )
    path = tmp_path / f"{name}.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _run(config: Path, out: Path) -> Path:
    result = CliRunner().invoke(
        app, ["run", "--config", str(config), "--tier", "pr", "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    return Path(result.stdout.strip().splitlines()[-1])


def test_good_against_bug_fails_on_tenant_leak(tmp_path: Path) -> None:
    good = _config(tmp_path, "good", GOOD_URL)
    bug = _config(tmp_path, "bug", BUG_URL)
    one = _run(good, tmp_path / "runs")
    two = _run(bug, tmp_path / "runs")
    args = ["gate", "--config", str(good), "--candidate", str(two), "--baseline", str(one)]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 1, result.output
    report = json.loads((two / "gate.json").read_text(encoding="utf-8"))
    assert "tenant_leak" in {h["metric"] for h in report["hard_fails"]}

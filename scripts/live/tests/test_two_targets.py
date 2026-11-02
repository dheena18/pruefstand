"""``scripts/live/two_targets.sh`` argument checks (the live test covers the stack)."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "live" / "two_targets.sh"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    command = [shutil.which("bash") or "bash", str(SCRIPT), *args]
    return subprocess.run(  # noqa: S603  (fixed argument list)
        command, capture_output=True, text=True, timeout=60, check=False
    )


def test_no_bug_name_prints_usage_with_the_known_bugs() -> None:
    done = _run()
    assert done.returncode == 2
    assert "usage" in done.stderr
    assert "tenant_filter_post_topk" in done.stderr
    assert "no_citations" in done.stderr


@pytest.mark.parametrize("bad", ["nonsense", "../rag", "tenant_filter_post_topk.yaml"])
def test_an_unknown_bug_is_refused_before_anything_starts(bad: str) -> None:
    done = _run(bad)
    assert done.returncode == 2
    assert "usage" in done.stderr

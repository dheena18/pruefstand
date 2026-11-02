"""Helpers of the live e2e gate tests (T1.11 S4): stack URLs, bug instances, timed CLI calls."""

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from typer.testing import CliRunner

from pruefstand.cli import app

ROOT = Path(__file__).resolve().parents[4]
CONFIGS = Path(__file__).resolve().parents[1] / "e2e" / "configs"
DATASET = ROOT / "datasets" / "fixtures" / "slice_v1"
GOOD_URL_ENV = "PRUEFSTAND_LIVE_GOOD_URL"
_MAKE = shutil.which("make") or "make"
_BASH = shutil.which("bash") or "bash"


@dataclass(frozen=True)
class Timed:
    """The result of a CLI call and how long it took."""

    exit_code: int
    output: str  # stdout and stderr, for failure messages
    stdout: str
    seconds: float


def good_url() -> str:
    """Base URL of the good rag-demo: the environment, else the port `make ports` reports."""
    if url := os.environ.get(GOOD_URL_ENV):
        return url
    done = subprocess.run(  # noqa: S603  (fixed argument list)
        [_MAKE, "--no-print-directory", "-C", str(ROOT), "ports"],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    match = re.search(r"^rag-demo (\d+)$", done.stdout, re.MULTILINE)
    assert match, f"make ports does not list rag-demo: {done.stdout!r}"
    return f"http://127.0.0.1:{match.group(1)}"


def healthy(url: str) -> bool:
    """Whether ``url`` answers ``/v1/health``."""
    try:
        return httpx.get(f"{url}/v1/health", timeout=5).is_success
    except httpx.HTTPError:
        return False


def start_bug(bug: str) -> str:
    """Start the bug instance with `scripts/live/two_targets.sh`; return its base URL."""
    done = subprocess.run(  # noqa: S603  (fixed argument list, the script checks the bug name)
        [_BASH, str(ROOT / "scripts" / "live" / "two_targets.sh"), bug],
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    assert done.returncode == 0, f"two_targets.sh {bug} failed:\n{done.stderr[-800:]}"
    match = re.search(r"bug=(http://\S+)", done.stdout)
    assert match, f"two_targets.sh printed no bug URL: {done.stdout!r}"
    return match.group(1)


def stop_bug(bug: str) -> None:
    """Remove the bug instance container (best effort)."""
    docker = shutil.which("docker")
    if docker:
        subprocess.run(  # noqa: S603  (fixed argument list)
            [docker, "rm", "-f", f"rag-demo-bug-{bug}"],
            capture_output=True,
            check=False,
            timeout=120,
        )


def write_config(scenario: str, url: str, tmp: Path) -> Path:
    """Copy the scenario config with the target URL and the absolute dataset path filled in."""
    text = (CONFIGS / f"{scenario}.yaml").read_text(encoding="utf-8")
    text = text.replace("http://localhost:8000", url).replace(
        "datasets/fixtures/slice_v1", str(DATASET)
    )
    path = tmp / f"{scenario}-{time.monotonic_ns()}.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def call(*args: str) -> Timed:
    """Invoke the real CLI in-process and time it."""
    started = time.monotonic()
    result = CliRunner().invoke(app, list(args))
    return Timed(result.exit_code, result.output, result.stdout, time.monotonic() - started)


def run_dir(done: Timed) -> Path:
    """The run directory a successful `run` printed on its last line."""
    assert done.exit_code == 0, done.output
    return Path(done.stdout.strip().splitlines()[-1])

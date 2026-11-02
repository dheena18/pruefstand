"""A misspelled `PRUEFSTAND_E2E_SCENARIO` or `SCENARIO` fails; it never passes by skipping (T1.11)."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from testsupport.e2e_support import SCENARIOS

ROOT = Path(__file__).resolve().parents[4]
E2E = "packages/pruefstand/tests/e2e"
MAKE = shutil.which("make") or "make"


def _pytest(scenario: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PRUEFSTAND_E2E_SCENARIO": scenario}
    return subprocess.run(  # noqa: S603  (fixed argument list)
        [sys.executable, "-m", "pytest", E2E, "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )


@pytest.mark.parametrize("name", ["goood", "good;ls", "GOOD", "test_good"])
def test_an_unknown_scenario_name_fails_the_pytest_run(name: str) -> None:
    done = _pytest(name)
    assert done.returncode != 0
    assert "PRUEFSTAND_E2E_SCENARIO" in done.stdout + done.stderr


@pytest.mark.parametrize("name", ["", "good", "injection_guard_off"])
def test_empty_and_known_names_collect(name: str) -> None:
    assert _pytest(name).returncode == 0


def _make(scenario: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  (fixed argument list)
        [MAKE, "-n", "e2e-live", f"SCENARIO={scenario}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_make_rejects_a_shell_metacharacter_value_without_running_anything(tmp_path: Path) -> None:
    marker = tmp_path / "pwned"
    done = _make(f"good; touch {marker}")
    assert done.returncode != 0
    assert not marker.exists()
    assert "SCENARIO" in done.stderr


@pytest.mark.parametrize("name", ["goood", "good bad", "$(shell id)"])
def test_make_rejects_unknown_names(name: str) -> None:
    assert _make(name).returncode != 0


def test_the_suite_is_bounded_by_a_timeout_and_the_names_match_the_tests() -> None:
    text = (ROOT / "mk" / "e2e.mk").read_text(encoding="utf-8")
    assert "timeout $(E2E_TIMEOUT) uv run pytest" in text
    assert "E2E_TIMEOUT ?= 3600" in text
    names = text.split("E2E_SCENARIOS :=")[1].splitlines()[0].split()
    assert names == list(SCENARIOS)

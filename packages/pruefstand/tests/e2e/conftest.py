"""Fixtures of the live e2e gate tests (T1.11 S4): the running `live` stack and the baseline run."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from testsupport.e2e_support import call, good_url, healthy, run_dir, write_config

BASELINE_ENV = (
    "PRUEFSTAND_E2E_BASELINE_RUN"  # CI shares one baseline run directory per workflow (T1.12)
)
SCENARIO_ENV = "PRUEFSTAND_E2E_SCENARIO"  # CI: one scenario per matrix job (T1.12)


@pytest.fixture(autouse=True)
def _tier1_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRUEFSTAND_STACK", "live")
    monkeypatch.setenv("PRUEFSTAND_JUDGE_MODE", "skipped")  # deterministic metrics only
    for name in ("GITHUB_TOKEN", "GH_TOKEN", "PRUEFSTAND_GH_MODELS_TOKEN"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _only_the_requested_scenario(request: pytest.FixtureRequest) -> None:
    wanted = os.environ.get(SCENARIO_ENV)
    if wanted and request.node.name != f"test_{wanted}":
        pytest.skip(f"{SCENARIO_ENV}={wanted}")


@pytest.fixture(scope="session")
def target_url() -> str:
    """URL of the good rag-demo; the session fails fast when the stack is not up."""
    url = good_url()
    if not healthy(url):
        pytest.fail(f"{url} is not healthy; run `make e2e-live` (stack up, slice indexed)")
    return url


@pytest.fixture(scope="session")
def baseline(
    target_url: str, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[tuple[Path, float]]:
    """The baseline run (good config, both splits), made once: ``(run directory, seconds)``."""
    shared = os.environ.get(BASELINE_ENV)
    if shared:
        yield Path(shared), 0.0
        return
    root = tmp_path_factory.mktemp("e2e-baseline")
    config = write_config("good", target_url, root)
    done = call("run", "--config", str(config), "--tier", "pr", "--out", str(root / "runs"))
    yield run_dir(done), done.seconds

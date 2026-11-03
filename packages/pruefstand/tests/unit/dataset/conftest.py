"""Shared fixtures of the dataset tests: one complete release build per test session."""

import numpy as np
import pytest
from testsupport.dataset_support import release_input

from pruefstand.core.config import SplitPlan
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.splits import assign_splits


@pytest.fixture(scope="session")
def release() -> list[TestCase]:
    """``assign_splits`` of a generator output with surplus, default plan, seed 11."""
    return assign_splits(release_input(), SplitPlan(), np.random.default_rng(11))


@pytest.fixture(autouse=True)
def _datagen_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The loopback backend reads its credential from this variable (a runtime-built dummy)."""
    monkeypatch.setenv("PRUEFSTAND_TEST_DATAGEN_KEY", "-".join(["dummy", "value"]))

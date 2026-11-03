"""The scripted loopback needs the key variable of the test backend."""

import pytest
from testsupport.perturb_support import KEY_ENV


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_ENV, "synthetic-test-value")

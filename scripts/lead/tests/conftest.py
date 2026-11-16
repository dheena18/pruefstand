"""Fixtures of the lead-script tests."""

from pathlib import Path

import pytest
from lead.leadtestenv import Lab


@pytest.fixture
def lab(tmp_path: Path) -> Lab:
    return Lab(tmp_path)

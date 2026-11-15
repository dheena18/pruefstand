"""Fixtures of the merge-script tests."""

from pathlib import Path

import pytest
from merge_reviewed_testenv import Env, make_template


@pytest.fixture(scope="module")
def template_origin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_template(tmp_path_factory.mktemp("template"))


@pytest.fixture
def env(tmp_path: Path, template_origin: Path) -> Env:
    return Env(tmp_path, template_origin)

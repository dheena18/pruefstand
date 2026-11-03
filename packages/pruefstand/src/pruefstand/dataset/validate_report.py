"""Collector of ``validate_dataset`` findings (problems; quota findings fixtures only log)."""

from itertools import pairwise
from pathlib import Path

from pruefstand.core.logging import get_logger

_log = get_logger(__name__)


def is_fixture(directory: Path) -> bool:
    """True for ``datasets/fixtures/*``: quota findings there are warnings (R9 D9-33)."""
    parts = directory.resolve().parts
    return any(a == "datasets" and b == "fixtures" for a, b in pairwise(parts))


class Findings:
    """Problems (returned) and quota findings (problems on real builds, logged on fixtures)."""

    def __init__(self, *, fixture: bool) -> None:
        self.fixture = fixture
        self.problems: list[str] = []

    def problem(self, message: str) -> None:
        """Record a problem that is always returned."""
        self.problems.append(message)

    def quota(self, message: str) -> None:
        """Record a quota finding: a problem, or a logged warning for a fixture dataset."""
        if self.fixture:
            _log.warning("dataset_quota_not_met", detail=message)
        else:
            self.problems.append(message)

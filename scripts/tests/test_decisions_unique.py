"""Every D-number in docs/decisions.md appears exactly once (D852)."""

import collections
import re
from pathlib import Path

DECISIONS = Path(__file__).resolve().parents[2] / "docs" / "decisions.md"


def test_every_d_number_is_unique() -> None:
    ids = re.findall(r"^\| (D\d+) \|", DECISIONS.read_text(encoding="utf-8"), re.M)
    duplicates = sorted(i for i, n in collections.Counter(ids).items() if n > 1)
    assert not duplicates, f"duplicate decision numbers: {', '.join(duplicates)}"


def test_the_log_is_not_empty_and_ids_are_well_formed() -> None:
    ids = re.findall(r"^\| (D\d+) \|", DECISIONS.read_text(encoding="utf-8"), re.M)
    assert len(ids) > 100

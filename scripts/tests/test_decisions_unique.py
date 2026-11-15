"""Decision files: ids are unique, id == file name, nothing is left in the old table (D852, D1211).

The log used to be one table in ``docs/decisions.md`` (D852: every D-number appears once). It is now
one file per decision, ``docs/decisions/D<n>.md``; the same guarantees hold on the new layout.
"""

import collections
import re
from pathlib import Path

from build_decisions_index import build_log, check
from decisions_files import ID_RE, load_dir, validate
from decisions_migrate import find_rows

DOCS = Path(__file__).resolve().parents[2] / "docs"
DIR = DOCS / "decisions"
OLD = DOCS / "decisions.md"


def test_every_d_number_is_unique() -> None:
    decisions, problems = load_dir(DIR)
    assert not problems, problems
    duplicates = sorted(i for i, n in collections.Counter(d.id for d in decisions).items() if n > 1)
    assert not duplicates, f"duplicate decision numbers: {', '.join(duplicates)}"


def test_the_log_is_not_empty_and_ids_are_well_formed() -> None:
    decisions, _ = load_dir(DIR)
    assert len(decisions) > 100
    assert all(ID_RE.match(d.id) for d in decisions)


def test_id_equals_file_name_and_the_directory_is_valid() -> None:
    assert validate(DIR) == []
    for path in DIR.glob("*.md"):
        assert path.read_text(encoding="utf-8").startswith(f'---\nid: "{path.stem}"\n')


def test_no_decision_row_is_left_in_the_old_table() -> None:
    """A stale branch that appends ``| D<n> | ... |`` to docs/decisions.md fails here (use
    ``scripts/build_decisions_index.py --migrate-pending``)."""
    rows = find_rows(OLD.read_text(encoding="utf-8"))
    assert [r.decision.id for r in rows] == []
    assert check(DIR, OLD) == []


def test_the_generated_log_is_deterministic_and_sorted() -> None:
    first = build_log(DIR)
    assert first == build_log(DIR)
    numbers = [int(line.split(" ")[1][1:]) for line in first.split("\n") if line.startswith("| D")]
    assert numbers == sorted(numbers)
    assert len(numbers) == len(set(numbers))


def test_the_hand_written_page_does_not_grow_decision_entries() -> None:
    """New decisions are files. The page keeps its 63 dated pre-number rows and no D-number
    entries (rows, headings, list items); pinned versions may still change."""
    text = OLD.read_text(encoding="utf-8")
    assert len(re.findall(r"(?m)^\| 20\d\d-\d\d-\d\d \|", text)) == 63
    assert not re.findall(r"(?m)^(#+ +|[-*] +\*{0,2}|\| *)D\d+\b[^|]*?(:|\*\*| \|)", text)
    assert not re.findall(r"(?m)^(<{7}|={7}|>{7})", text)

"""Move old-style rows of ``docs/decisions.md`` into ``docs/decisions/D<n>.md`` (D1211).

Used twice: once for the initial migration of the 683 existing rows (the check below proved it
loss-free), and afterwards by ``build_decisions_index.py --migrate-pending`` for PRs that were
branched before the layout change and still append a ``| D<n> | ... |`` row to the old table. The
move is idempotent: a row whose file already exists with the same content is just removed from
the old file; a row whose file exists with *different* content is a conflict and nothing is
written.
"""

import collections
import re
from dataclasses import dataclass
from pathlib import Path

from decisions_files import (
    CONFLICT_RE,
    ROW_START,
    ConflictMarkerError,
    Decision,
    DecisionError,
    join_row,
    parse_file,
    render_file,
    split_row,
    to_doc_links,
    to_file_links,
)

APPENDED_SECTION = "Task decisions (appended by tasks)"


@dataclass(frozen=True)
class ParsedRow:
    """A decision row found in a Markdown file.

    Attributes:
        line_no: Zero-based index of the line.
        decision: The parsed decision.
    """

    line_no: int
    decision: Decision


def _is_decision_header(cells: list[str]) -> bool:
    return len(cells) >= 2 and cells[0] == "#" and cells[1] == "Decision"


def _extra_name(header: str) -> str:
    return "_".join(header.lower().split())


def _merge_split_code(cells: list[str]) -> list[str]:
    """Re-join a text cell that an unescaped `` | `` inside a code span split into two cells.

    >>> _merge_split_code(["D1", "a `X", "None` b", "adr"])
    ['D1', 'a `X | None` b', 'adr']
    """
    cells = list(cells)
    while len(cells) > 2 and cells[1].count("`") % 2 == 1:
        cells[1:3] = [cells[1] + " | " + cells[2]]
    return cells


LOOSE_ROW = re.compile(r"^\s*\|\s*(D[0-9]+)\s*\|")
# A decision-style entry that is not a table row: heading, list item or prose starting with D<n>.
_ENTRY = re.compile(
    r"^\s*(\|\s*D[0-9]+\s*\||#+\s+D[0-9]{1,5}\b|[-*]\s+\**D[0-9]{1,5}\b|D[0-9]{1,5}\b)"
)


def loose_entries(text: str) -> list[tuple[int, str]]:
    r"""Lines that look like a decision entry in any form (tight or indented rows, headings, prose).

    >>> loose_entries("|D5|x|\n### D6 new\nD7 is: x\n| 2026-01-01 | T0 | y | z |\nDense")
    [(0, '|D5|x|'), (1, '### D6 new'), (2, 'D7 is: x')]
    """
    return [(i, ln) for i, ln in enumerate(text.split("\n")) if _ENTRY.match(ln)]


def _row_cells(line: str) -> list[str]:
    if ROW_START.match(line) and line.endswith(" |"):
        return split_row(line)
    inner = line.strip().removeprefix("|").removesuffix("|")
    return [c.strip() for c in re.split(r"(?<!\\)\|", inner)]


def find_rows(text: str) -> list[ParsedRow]:
    """Find every ``| D<n> | ... |`` row of a Markdown text.

    Args:
        text: Content of the old ``decisions.md``.

    Returns:
        The rows in file order. The section is the nearest ``## `` heading when the row sits under
        a ``# | Decision | ...`` table header, else ``"Task decisions (appended)"``. Extra
        columns are named after the header when the cell count matches it, else ``col3``, ``col4``.
        A text cell with an odd number of backticks was split by a literal `` | `` in a code span
        (``X | None``); it is re-joined.

    Raises:
        DecisionError: when a row cannot be split.
    """
    heading = ""
    header: list[str] = []
    rows: list[ParsedRow] = []
    for no, line in enumerate(text.split("\n")):
        if line.startswith("## "):
            heading, header = line[3:].strip(), []
        elif line.startswith("| #") or line.startswith("| Date"):
            header = split_row(line) if line.endswith(" |") else []
        elif LOOSE_ROW.match(line):
            cells = _merge_split_code(_row_cells(line))
            known = _is_decision_header(header) and len(header) == len(cells)
            names = [_extra_name(h) for h in header[2:]] if known else []
            if not known:
                names = [f"col{i}" for i in range(3, len(cells) + 1)]
            section = heading if _is_decision_header(header) else APPENDED_SECTION
            extras = tuple(zip(names, cells[2:], strict=True))
            rows.append(ParsedRow(no, Decision(cells[0], section, cells[1], extras)))
    return rows


def row_line(d: Decision) -> str:
    """Rebuild the old table row of a decision.

    >>> row_line(Decision("D1", "S", "t", (("adr", "a"),)))
    '| D1 | t | a |'
    """
    return join_row([d.id, d.text, *[v for _, v in d.extras]])


def as_file(d: Decision) -> Decision:
    """The decision as stored in a file: links re-based to ``docs/decisions/``."""
    return Decision(
        d.id, d.section, to_file_links(d.text), tuple((k, to_file_links(v)) for k, v in d.extras)
    )


def as_doc(d: Decision) -> Decision:
    """Inverse of :func:`as_file`: links relative to ``docs/`` again (the old row)."""
    return Decision(
        d.id, d.section, to_doc_links(d.text), tuple((k, to_doc_links(v)) for k, v in d.extras)
    )


def migrate(decisions_md: Path, out_dir: Path) -> list[str]:
    """Move all decision rows of ``decisions_md`` into files of ``out_dir``.

    Args:
        decisions_md: The old log; rewritten without the moved rows.
        out_dir: ``docs/decisions``; created when missing.

    Returns:
        The ids of the files newly written, in file order (rows whose identical file already
        exists are removed from ``decisions_md`` but not listed).

    Raises:
        ConflictMarkerError: when ``decisions_md`` holds git conflict markers (nothing written).
        DecisionError: on a duplicate id among the rows, or when a file of that id exists with
            different content. Nothing is written in that case.
    """
    text = decisions_md.read_text(encoding="utf-8")
    if CONFLICT_RE.search(text):
        msg = f"{decisions_md.name} contains git conflict markers; resolve the merge first"
        raise ConflictMarkerError(msg)
    rows = [ParsedRow(r.line_no, as_file(r.decision)) for r in find_rows(text)]
    counts = collections.Counter(r.decision.id for r in rows)
    dups = sorted(i for i, n in counts.items() if n > 1)
    if dups:
        msg = f"duplicate ids in {decisions_md.name}: {', '.join(dups)}"
        raise DecisionError(msg)
    writes: list[tuple[Path, str]] = []
    for r in rows:
        path = out_dir / f"{r.decision.id}.md"
        new = render_file(r.decision)
        if path.exists():
            old = parse_file(path.read_text(encoding="utf-8"), path.name)
            if old.text != r.decision.text or old.extras != r.decision.extras:
                msg = f"{path.name} exists with different content (id clash)"
                raise DecisionError(msg)
            continue
        writes.append((path, new))
    out_dir.mkdir(parents=True, exist_ok=True)
    for path, new in writes:
        path.write_text(new, encoding="utf-8")
    drop = {r.line_no for r in rows}
    kept = [ln for i, ln in enumerate(text.split("\n")) if i not in drop]
    if drop:
        decisions_md.write_text("\n".join(kept), encoding="utf-8")
    return [path.stem for path, _ in writes]


def roundtrip_problems(original_text: str, out_dir: Path) -> list[str]:
    """Prove a migration loss-free: old rows (as lines) equal the rows rebuilt from the files.

    Args:
        original_text: The old ``decisions.md`` before :func:`migrate`.
        out_dir: Directory holding the migrated files.

    Returns:
        Differences as text; empty when the multiset of ``(id, text, extra columns)`` and of the
        rebuilt row lines are both identical.
    """
    before = [as_file(r.decision) for r in find_rows(original_text)]
    after = [
        parse_file(p.read_text(encoding="utf-8"), p.name) for p in sorted(out_dir.glob("D*.md"))
    ]
    out: list[str] = []
    key = lambda d: (d.id, d.text, d.extras)  # noqa: E731
    if collections.Counter(map(key, before)) != collections.Counter(map(key, after)):
        out.append("multiset of (id, text, extras) differs")
    lines_before = collections.Counter(r for r in original_text.split("\n") if ROW_START.match(r))
    lines_after = collections.Counter(row_line(as_doc(d)) for d in after)
    if lines_before != lines_after:
        out.append("rebuilt row lines differ from the original lines")
    return out

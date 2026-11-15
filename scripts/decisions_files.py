"""One file per decision: ``docs/decisions/D<n>.md`` (D1211).

Why: every PR used to append a row at the end of one big table in ``docs/decisions.md``, so two
PRs always conflicted. A decision is now a file of its own. Two PRs add two different files, which
git merges without a conflict. The human-readable single log is *generated*
(``docs/decisions-log.md``,
git-ignored) by ``scripts/build_decisions_index.py``.

File format (all values are JSON strings, so the front matter is valid YAML and loss-free)::

    ---
    id: "D12"
    section: "Architecture and process (2026-10-27)"
    adr: "[0012](adr/0012-demo-hosting-separate.md)"
    ---

    <the decision text, verbatim from the old table cell>

``id`` and ``section`` come first; every further key is one more column of the old row, in order
(``supersedes``, ``adr``, or ``col<n>`` where the old table had no usable header).
"""

import json
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path

ID_RE = re.compile(r"^D[1-9][0-9]*$")
_KEY_RE = re.compile(r"^([a-z][a-z0-9_]*): (.*)$")
FRONT_FENCE = "---"
# Cell separator of a Markdown table row; an escaped pipe (backslash + pipe) is not a separator.
_CELL_SPLIT = re.compile(r"(?<!\\) \| ")
ROW_START = re.compile(r"^\| (D[0-9]+) \| ")


_LINK = re.compile(r"(\]\()([^)\s#]+)(#[^)\s]*)?(\))")
_SCHEME = re.compile(r"^([a-z][a-z0-9+.-]*:|/)", re.IGNORECASE)


def _relink(text: str, prefix: str) -> str:
    def fix(m: re.Match[str]) -> str:
        target = m.group(2)
        if _SCHEME.match(target):
            return m.group(0)
        moved = posixpath.normpath(posixpath.join(prefix, target))
        return f"{m.group(1)}{moved}{m.group(3) or ''}{m.group(4)}"

    return _LINK.sub(fix, text)


def to_file_links(text: str) -> str:
    """Re-base relative Markdown links from ``docs/`` to ``docs/decisions/`` (file location).

    >>> to_file_links("[a](adr/1.md#x) [b](https://e.org/a) [c](../tasks/T.md)")
    '[a](../adr/1.md#x) [b](https://e.org/a) [c](../../tasks/T.md)'
    """
    return _relink(text, "..")


def to_doc_links(text: str) -> str:
    """Inverse of :func:`to_file_links` (the generated log lives in ``docs/``).

    >>> to_doc_links("[a](../adr/1.md#x) [c](../../tasks/T.md)")
    '[a](adr/1.md#x) [c](../tasks/T.md)'
    """
    return _relink(text, "decisions")


class DecisionError(ValueError):
    """A decision file or row is malformed."""


class ConflictMarkerError(DecisionError):
    """A file still holds git merge conflict markers; resolve the merge first."""


CONFLICT_RE = re.compile(r"(?m)^(<{7}( .*)?|={7}|>{7}( .*)?)$")


@dataclass(frozen=True)
class Decision:
    """One decision.

    Attributes:
        id: ``D<n>``, equal to the file stem.
        section: Heading the row lived under in the old log (free text, may be empty).
        text: The decision text (the second table cell), verbatim.
        extras: Further columns of the old row as ordered ``(key, value)`` pairs.
    """

    id: str
    section: str
    text: str
    extras: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def number(self) -> int:
        """The numeric part of the id.

        >>> Decision("D12", "", "x").number
        12
        """
        return int(self.id[1:])


def split_row(line: str) -> list[str]:
    """Split a Markdown table row into its cells (verbatim, escaped pipes kept).

    >>> split_row("| D1 | a | c |")
    ['D1', 'a', 'c']

    Raises:
        DecisionError: if ``line`` is not a row of the form ``| a | b |``.
    """
    if not (line.startswith("| ") and line.endswith(" |")):
        msg = f"not a table row: {line[:60]!r}"
        raise DecisionError(msg)
    return _CELL_SPLIT.split(line[2:-2])


def join_row(cells: list[str]) -> str:
    """Inverse of :func:`split_row`.

    >>> join_row(["D1", "a", ""])
    '| D1 | a |  |'
    """
    return "| " + " | ".join(cells) + " |"


def render_file(d: Decision) -> str:
    """Serialise a decision to the text of its file.

    >>> print(render_file(Decision("D7", "S", "Text.", (("adr", "[1](a.md)"),))), end="")
    ---
    id: "D7"
    section: "S"
    adr: "[1](a.md)"
    ---
    <BLANKLINE>
    Text.
    """
    head = [f"id: {_js(d.id)}", f"section: {_js(d.section)}"]
    head += [f"{k}: {_js(v)}" for k, v in d.extras]
    return "\n".join([FRONT_FENCE, *head, FRONT_FENCE, "", d.text, ""])


def parse_file(text: str, source: str = "<text>") -> Decision:
    """Parse the text of a decision file.

    Args:
        text: File content.
        source: Name used in error messages.

    Returns:
        The decision.

    Raises:
        DecisionError: on a missing front matter, a bad line, a missing ``id``/``section`` or an
            empty body.
    """
    if CONFLICT_RE.search(text):
        msg = f"{source}: contains git conflict markers"
        raise ConflictMarkerError(msg)
    lines = text.split("\n")
    if not lines or lines[0] != FRONT_FENCE:
        msg = f"{source}: must start with a '---' front matter"
        raise DecisionError(msg)
    try:
        end = lines.index(FRONT_FENCE, 1)
    except ValueError:
        msg = f"{source}: front matter is not closed"
        raise DecisionError(msg) from None
    pairs: list[tuple[str, str]] = []
    for raw in lines[1:end]:
        m = _KEY_RE.match(raw)
        if m is None:
            msg = f"{source}: bad front matter line {raw!r}"
            raise DecisionError(msg)
        value = _unjs(m.group(2), source)
        pairs.append((m.group(1), value))
    keys = [k for k, _ in pairs]
    if keys[:2] != ["id", "section"] or len(set(keys)) != len(keys):
        msg = f"{source}: front matter must start with id, section; keys unique"
        raise DecisionError(msg)
    body = "\n".join(lines[end + 1 :]).strip("\n")
    if not body:
        msg = f"{source}: empty decision text"
        raise DecisionError(msg)
    return Decision(pairs[0][1], pairs[1][1], body, tuple(pairs[2:]))


def _js(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _unjs(raw: str, source: str) -> str:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        msg = f"{source}: value is not a JSON string: {raw[:40]!r}"
        raise DecisionError(msg) from None
    if not isinstance(value, str):
        msg = f"{source}: value is not a string: {raw[:40]!r}"
        raise DecisionError(msg)
    return value


def load_dir(directory: Path) -> tuple[list[Decision], list[str]]:
    """Load every ``D*.md`` of a decisions directory.

    Args:
        directory: ``docs/decisions``.

    Returns:
        ``(decisions sorted by number, problems)``; a file that fails to parse is a problem and
        skipped.
    """
    found: list[Decision] = []
    problems: list[str] = []
    for path in sorted(directory.glob("*.md")):
        try:
            found.append(parse_file(path.read_text(encoding="utf-8"), path.name))
        except DecisionError as exc:
            problems.append(str(exc))
            continue
        problems += _name_problems(path, found[-1])
    found.sort(key=lambda d: d.number if ID_RE.match(d.id) else -1)
    return found, problems


def _name_problems(path: Path, d: Decision) -> list[str]:
    out: list[str] = []
    if not ID_RE.match(d.id):
        out.append(f"{path.name}: id {d.id!r} is not D<number> (no leading zeros)")
    if path.stem != d.id:
        out.append(f"{path.name}: id {d.id!r} must equal the file name {path.stem!r}")
    return out


def validate(directory: Path) -> list[str]:
    """Check the whole directory.

    Rules: every file parses; ``id`` equals the file stem and is ``D<number>`` without leading
    zeros; ids are unique (also case-insensitively, so ``d5.md`` cannot shadow ``D5.md``); no file
    other than ``D<n>.md`` lives in the directory.

    Returns:
        Human-readable problems; empty when the directory is fine.
    """
    decisions, problems = load_dir(directory)
    seen: dict[str, int] = {}
    for d in decisions:
        seen[d.id.lower()] = seen.get(d.id.lower(), 0) + 1
    problems += [f"duplicate decision id {k.upper()}" for k, n in sorted(seen.items()) if n > 1]
    for path in sorted(directory.iterdir()):
        if not re.fullmatch(r"D[1-9][0-9]*\.md", path.name):
            problems.append(f"{path.name}: only D<number>.md files belong in {directory.name}/")
    if not decisions:
        problems.append(f"no decision files in {directory}")
    return problems


def render_log(decisions: list[Decision]) -> str:
    """Render the single generated log (deterministic, sorted numerically).

    Args:
        decisions: Any order; sorted here by number.

    Returns:
        A Markdown page with one table ``# | Decision | Supersedes | ADR | Source | Extra``
        (``Extra`` = the unnamed ``col<n>`` columns). Same input, same output.
    """
    ordered = sorted(decisions, key=lambda d: d.number)
    head = ["#", "Decision", "Supersedes", "ADR", "Source", "Extra"]
    lines = [
        "# Decision log (generated)",
        "",
        "Generated from `docs/decisions/D<n>.md` by `scripts/build_decisions_index.py`; not",
        "committed, do not edit. To add a decision, create `docs/decisions/D<n>.md` (D1211).",
        "",
        join_row(head),
        join_row(["---"] * len(head)),
    ]
    for d in ordered:
        extra = dict(d.extras)
        rest = "; ".join(
            f"{k}: {to_doc_links(v)}" for k, v in d.extras if k not in ("supersedes", "adr")
        )
        cells = [
            d.id,
            to_doc_links(d.text),
            to_doc_links(extra.get("supersedes", "")),
            to_doc_links(extra.get("adr", "")),
            d.section,
            rest.replace("|", "\\|"),
        ]
        lines.append(join_row(cells))
    return "\n".join(lines) + "\n"

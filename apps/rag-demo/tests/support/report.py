"""The Markdown report of the tier-2 quality run (T3.7) and the carry-over of human verdicts.

``render`` writes the table; ``read_verdicts`` reads the **Human verdict (S4)** column of an
existing report, so a re-run never overwrites what a person entered (a verdict stays with its
question id; an answer that changed is still marked so the reader re-checks it).
"""

import re
from collections.abc import Mapping, Sequence

VERDICT = "Human verdict (S4)"
PENDING = "_pending (S4)_"
COLUMNS = (
    "#", "Tenant", "Question", "Answer", "Citations", "Expected", "Citation ok", "Key fact ok",
    "Language ok", "Auto pass", VERDICT,
)  # fmt: skip
_PIPE = re.compile(r"(?<!\\)\|")
_YES = {True: "yes", False: "**no**"}


def cell(text: object) -> str:
    """A table cell: pipes escaped, newlines as ``<br>``.

    Examples:
        >>> cell("a|b\\nc")
        'a\\\\|b<br>c'
    """
    return str(text).replace("|", "\\|").replace("\n", "<br>")


def uncell(text: str) -> str:
    """The inverse of ``cell``."""
    return text.replace("<br>", "\n").replace("\\|", "|")


def table_rows(markdown: str) -> list[dict[str, str]]:
    """The rows of the report table as ``{column: raw cell}`` (header from the table itself)."""
    lines = markdown.splitlines()
    head = next(
        (i for i, line in enumerate(lines) if VERDICT in line and line.startswith("|")), None
    )
    if head is None:
        return []
    names = [c.strip() for c in _PIPE.split(lines[head])[1:-1]]
    rows = []
    for line in lines[head + 2 :]:
        if not line.startswith("|"):
            break
        cells = [c.strip() for c in _PIPE.split(line)[1:-1]]
        rows.append(dict(zip(names, cells, strict=True)))
    return rows


def read_verdicts(markdown: str) -> dict[str, str]:
    """The human verdicts already entered, by question id (pending ones left out)."""
    return {r["#"]: r[VERDICT] for r in table_rows(markdown) if r.get(VERDICT, PENDING) != PENDING}


def render(
    meta: Mapping[str, str], rows: Sequence[Mapping[str, object]], verdicts: Mapping[str, str]
) -> str:
    """The report: run facts, then one table row per question with the carried-over verdict."""
    lines = [
        "# T3.7 tier-2 report: leak probes and the 10 German quality questions",
        "",
        "Written by `test_quality_and_isolation.py` (`make test-gpu` on the VM).",
        "The **Human verdict** column is S4: a person who reads German marks each answer",
        "`correct` / `incorrect` (with a short reason). The automatic checks never fill it.",
        "",
        *(f"- {key}: `{cell(value)}`" for key, value in meta.items()),
        "",
        "| " + " | ".join(COLUMNS) + " |",
        "| " + " | ".join("---" for _ in COLUMNS) + " |",
    ]
    for r in rows:
        values = [
            r["id"], r["tenant"], cell(r["question"]), cell(r["answer"]),
            cell(", ".join(map(str, r["citations"]))),  # type: ignore[call-overload]  # list
            cell(", ".join(map(str, r["expected"]))),  # type: ignore[call-overload]  # list
            *(_YES[bool(r[k])] for k in ("citation", "key_fact", "language", "passed")),
            verdicts.get(str(r["id"]), PENDING),
        ]  # fmt: skip
        lines.append("| " + " | ".join(map(str, values)) + " |")
    return "\n".join(lines) + "\n"

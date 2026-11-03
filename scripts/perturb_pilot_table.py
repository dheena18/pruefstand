r"""Render the T4.5 pilot table from the output of ``python -m pruefstand.perturb --questions``.

    python -m pruefstand.perturb --questions datasets/fixtures/perturb_pilot_questions.txt \
        --name compound_split,register,gender,colloquial --model ... --judge-model ... \
        --pass both > pilot.tsv
    python scripts/perturb_pilot_table.py datasets/fixtures/perturb_pilot_questions.txt pilot.tsv

Validity rate = valid / applicable, where applicable excludes ``not_applicable`` (no compound, no
Sie/du marker, no table noun) and ``unchanged`` (the model kept a compound with no paraphrase).
"""

import sys
from collections import defaultdict
from pathlib import Path

NOT_APPLICABLE = {"not_applicable", "unchanged"}


def load_questions(path: Path) -> list[str]:
    """Return the questions of the fixture file (comments and blank lines dropped)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def render(questions: list[str], tsv: str) -> str:
    """Return the markdown table and the validity rates.

    Args:
        questions: The pilot questions, in order (``q01`` is the first).
        tsv: Output lines ``qNN<TAB>name<TAB>valid=True<TAB>text`` or
            ``qNN<TAB>name<TAB>valid=False<TAB>reason=<why><TAB>original``.

    Returns:
        Markdown: one row per (question, perturbation), then a rate table.
    """
    rows = ["| id | perturbation | before | after / reason |", "| --- | --- | --- | --- |"]
    counts: dict[str, dict[str, int]] = defaultdict(lambda: {"valid": 0, "applicable": 0})
    for line in tsv.splitlines():
        parts = line.split("\t")
        if len(parts) < 4 or not parts[0].startswith("q"):
            continue
        qid, name, flag = parts[0], parts[1], parts[2]
        before = questions[int(qid[1:]) - 1]
        valid = flag == "valid=True"
        detail = parts[3] if valid else parts[3].removeprefix("reason=")
        if valid or detail not in NOT_APPLICABLE:
            counts[name]["applicable"] += 1
            counts[name]["valid"] += int(valid)
        rows.append(f"| {qid} | {name} | {before} | {detail} |")
    rows += [
        "",
        "| perturbation | valid | applicable | validity rate |",
        "| --- | --- | --- | --- |",
    ]
    for name, c in counts.items():
        rate = c["valid"] / c["applicable"] if c["applicable"] else 0.0
        rows.append(f"| {name} | {c['valid']} | {c['applicable']} | {rate:.0%} |")
    return "\n".join(rows) + "\n"


def main(argv: list[str]) -> int:
    """CLI: ``perturb_pilot_table.py QUESTIONS.txt OUTPUT.tsv``; prints the markdown."""
    if len(argv) != 2:
        sys.stderr.write("usage: perturb_pilot_table.py QUESTIONS.txt OUTPUT.tsv\n")
        return 2
    sys.stdout.write(render(load_questions(Path(argv[0])), Path(argv[1]).read_text("utf-8")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

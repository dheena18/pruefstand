"""Files of ``scripts/filter_qa.py``: outputs, the support-verdict log and the generator model."""

import json
from pathlib import Path

from generate_qa_ledger import dump_line, read_ledger, write_lines

from pruefstand.core.errors import ConfigError
from pruefstand.core.models.dataset import FilterResult, QACandidate
from pruefstand.dataset.filters import FilterOutcome
from pruefstand.dataset.to_case import case_id_of

VERDICTS = "support_verdicts.jsonl"
REPORT = "filter_report.json"


def read_verdicts(out_dir: Path, model: str) -> dict[str, FilterResult]:
    """Verdicts of an earlier run for ``model`` (a ``judge_error`` is not a verdict)."""
    path = out_dir / VERDICTS
    known: dict[str, FilterResult] = {}
    if not path.is_file():
        return known
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            if row["model"] == model and "judge_error" not in row["reasons"]:
                known[str(row["id"])] = FilterResult(
                    kept=bool(row["kept"]), reasons=tuple(row["reasons"])
                )
        except (ValueError, KeyError, TypeError):
            continue  # a damaged last line of a killed run
    return known


def append_verdict(out_dir: Path, c: QACandidate, model: str, verdict: FilterResult) -> None:
    """Append one fresh verdict to the log and flush it, so a later failure does not lose it."""
    row = {"id": case_id_of(c), "model": model, "kept": verdict.kept, "reasons": verdict.reasons}
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / VERDICTS).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
        handle.flush()


def generator_model(given: str | None, run_dir: Path) -> str:
    """The model that wrote the candidates: ``--generator-model``, else the ledger's (one model).

    Raises:
        ConfigError: Nothing is given and the ledger names none or several; or the given model is
            not one the ledger names.
    """
    models = {key.split("|")[1] for key in read_ledger(run_dir) if key.count("|") >= 2}
    if given is not None:
        if models and given not in models:
            msg = f"--generator-model {given} is not in the ledger of the run ({sorted(models)})"
            raise ConfigError(msg)
        return given
    if len(models) != 1:
        msg = "cannot tell the generator model from the ledger; pass --generator-model"
        raise ConfigError(msg)
    return next(iter(models))


def kept_name(outcome: FilterOutcome) -> str:
    """``filtered.jsonl`` only for a complete run; others get a name that says what they are."""
    report = outcome.report
    if report.support == "skipped":
        return "filtered_nosupport.jsonl"
    if report.not_checked or report.reasons.get("judge_error"):
        return "filtered_partial.jsonl"
    return "filtered.jsonl"


def write_outputs(out_dir: Path, run_dir: Path, outcome: FilterOutcome) -> str:
    """Write kept / dropped / unjudged files, the report and the ``filter`` part of summary.json."""
    name = kept_name(outcome)
    write_lines(out_dir / name, [dump_line(c) for c in outcome.kept])
    write_lines(out_dir / "filtered_out.jsonl", [dump_line(d) for d in outcome.dropped])
    write_lines(out_dir / "filtered_unjudged.jsonl", [dump_line(c) for c in outcome.unjudged])
    text = json.dumps(outcome.report.model_dump(mode="json"), indent=1, sort_keys=True)
    (out_dir / REPORT).write_text(text + "\n", encoding="utf-8")
    summary = run_dir / "summary.json"
    if summary.is_file():
        data = json.loads(summary.read_text(encoding="utf-8"))
        report = outcome.report
        data["filter"] = {
            "kept_file": name,
            "support": report.support,
            "support_model": report.support_model,
            "generator_model": report.generator_model,
            "complete": name == "filtered.jsonl",
            "not_checked": report.not_checked,
        }
        summary.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return name

"""Re-calibration of one pinned judge (T5.4 S11; X3.3, D163, D253).

``uv run python experiments/rq2/recalibrate.py --judge ollama/gemma3:12b`` re-runs the pass rule on
the full ``test`` sets from the judge's current verdicts (run ``run_judges.py`` first). On a pass it
bumps ``judge_epoch`` (the ``eval_fingerprint`` changes, so ``no_baseline`` until
``baseline-promote``) and clears the judge's drift flag; on a failure nothing changes and the flag
stays. Clearing a local judge's flag after a passing anchor re-run needs no epoch bump
(``after_anchor_rerun``; ``pruefstand judge-drift`` does it for Ollama judges).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run as a script: import rq2.*

from rq2.status_file import STATUS_PATH, epoch_of, read_document, write_document

from pruefstand.core.settings import PruefstandSettings
from pruefstand.llm.cache_epochs import clear_drift
from pruefstand.pipeline.judge_drift import DriftResult


def apply_recalibration(
    judge: str, *, passed: bool, cache_dir: Path, status_path: Path = STATUS_PATH
) -> int:
    """Record a re-calibration result; return the (possibly bumped) ``judge_epoch``.

    A pass bumps ``epoch`` by one and calls ``clear_drift``; a failure changes nothing.
    """
    doc = read_document(status_path)
    epoch = epoch_of(doc)
    if not passed:
        return epoch
    doc["epoch"] = epoch + 1
    write_document(doc, status_path)
    clear_drift(cache_dir, judge)
    return epoch + 1


def after_anchor_rerun(judge: str, result: DriftResult, cache_dir: Path) -> bool:
    """Clear a local judge's drift flag when its anchor re-run passed (no epoch bump, AI11-10)."""
    if result.status == "ok" and judge.startswith("ollama/"):
        clear_drift(cache_dir, judge)
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    """Re-run the pass rule for ``--judge`` and apply the result."""
    from rq2.report import evaluate_judge  # noqa: PLC0415 - heavy import only for the CLI

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--judge", required=True)
    args = parser.parse_args(argv)
    passed = evaluate_judge(args.judge)
    epoch = apply_recalibration(args.judge, passed=passed, cache_dir=PruefstandSettings().cache_dir)
    sys.stdout.write(f"{args.judge}: passed={passed} judge_epoch={epoch}\n")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

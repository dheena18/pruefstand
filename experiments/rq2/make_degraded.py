"""Degraded answer pairs for the discrimination check (T5.4 S3, T5.4b).

From the ``test`` positives (top label) of ``correctness`` and ``faithfulness_constructed`` take up
to 50 answers per edit type that the T5.3 edits change: ``swap_first_number`` and ``negate``
(``rq2.construct``). Order: seeded permutation of the item ids, so the pairs are deterministic.
A judge discriminates when it scores the degraded answer strictly lower; it passes with
>= 90 % per edit type (D146 (3)). Only 21 ``correctness`` test positives admit ``negate``
(short annotator spans, D932), so T5.4b fills that cell to 50 with sentence answers: the
GermanQuAD source sentence of a positive span and its negation (``rq2.sentence_answers``, D1240).
Every pair has ``form``: ``span`` (the item's own answer) or ``sentence``.

    uv run python experiments/rq2/make_degraded.py
    # -> datasets/calibration/v1/degraded_pairs_germanquad.jsonl (CC BY 4.0, ``correctness``)
    #    datasets/calibration/v1/degraded_pairs_germanrag.jsonl (CC BY-SA 4.0, faithfulness)
    # one file per licence, never mixed (D864, D946)
"""

import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run as a script: import rq2.*

from rq2.calib_schema import CalibrationItem, is_positive
from rq2.calib_sources import GERMANQUAD_TEST, QuadRow, load_germanquad
from rq2.construct import negate, swap_first_number
from rq2.rq2_config import REPO, load_config, load_items
from rq2.sentence_answers import match_row, negated_sentence

from pruefstand.core.errors import ConfigError

PAIRS_PER_EDIT = 50
SETS = ("correctness", "faithfulness_constructed")
EDITS: dict[str, Callable[[str], str | None]] = {
    "swap_first_number": swap_first_number,
    "negate": negate,
}
#: One file per source licence, never mixed (D864, D946):
#: GermanQuAD CC BY 4.0, GermanRAG CC BY-SA 4.0.
OUT: dict[str, Path] = {
    "correctness": Path("datasets/calibration/v1/degraded_pairs_germanquad.jsonl"),
    "faithfulness_constructed": Path("datasets/calibration/v1/degraded_pairs_germanrag.jsonl"),
}


def _pair(
    item: CalibrationItem, set_name: str, edit: str, *, base: dict[str, str], worse: str, form: str
) -> dict[str, object]:
    suffix = "" if form == "span" else f"_{form}"
    return {
        "pair_id": f"{item.item_id}:{edit}{suffix}",
        "label_set": set_name,
        "edit": edit,
        "form": form,
        "base_item_id": item.item_id,
        "cluster_id": item.cluster_id,
        "metric": item.metric,
        "inputs": base,
        "degraded": {**base, "antwort": worse},
    }


def _negated(row: QuadRow, item: CalibrationItem) -> tuple[str, str] | None:
    """The negated source sentence of the item's answer span, else of the reference span."""
    got = negated_sentence(row, item.inputs["antwort"])
    return got if got is not None else negated_sentence(row, item.inputs["referenz"])


def _sentence_pairs(
    ordered: Sequence[CalibrationItem], used: set[str], rows: Sequence[QuadRow], need: int
) -> list[dict[str, object]]:
    """Up to ``need`` sentence ``negate`` pairs from the positives not used by a span pair."""
    pairs: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in ordered:
        row = None if item.item_id in used else match_row(item, rows)
        got = None if row is None else _negated(row, item)
        if got is None or len(pairs) >= need or row is None or row.qid in seen:
            continue
        seen.add(row.qid)
        base = {**item.inputs, "antwort": got[0]}
        pairs.append(_pair(item, "correctness", "negate", base=base, worse=got[1], form="sentence"))
    return pairs


def make_pairs(
    items: Sequence[CalibrationItem],
    set_name: str,
    seed: int = 1234,
    per_edit: int = PAIRS_PER_EDIT,
    quad_rows: Sequence[QuadRow] | None = None,
) -> list[dict[str, object]]:
    """Return up to ``per_edit`` (base, degraded) pairs per edit type from top-label items.

    Args:
        items: One label set (only top-label items are used).
        set_name: Its name, written to every pair.
        seed: Seed of the order.
        per_edit: Pairs per edit type.
        quad_rows: GermanQuAD source rows; when given, the ``negate`` cell is filled up to
            ``per_edit`` with sentence pairs after the span pairs (T5.4b).

    Returns:
        Pair rows: ``pair_id, label_set, edit, form, base_item_id, cluster_id, metric, inputs,
        degraded``.
    """
    positives = sorted((i for i in items if is_positive(i)), key=lambda i: i.item_id)
    order = np.random.default_rng(seed).permutation(len(positives))
    ordered = [positives[int(idx)] for idx in order]
    pairs: list[dict[str, object]] = []
    for edit, fn in EDITS.items():
        taken: list[str] = []
        for item in ordered:
            changed = fn(item.inputs["antwort"])
            if changed is None or changed == item.inputs["antwort"] or len(taken) >= per_edit:
                continue
            pairs.append(
                _pair(item, set_name, edit, base=dict(item.inputs), worse=changed, form="span")
            )
            taken.append(item.item_id)
        if edit == "negate" and quad_rows is not None:
            pairs += _sentence_pairs(ordered, set(taken), quad_rows, per_edit - len(taken))
    return pairs


def discrimination(pairs: Sequence[tuple[int, int]]) -> float:
    """Share of (base score, degraded score) pairs with the degraded one strictly lower.

    >>> discrimination([(2, 0), (2, 2), (1, 0), (2, 1)])
    0.75
    """
    if not pairs:
        return float("nan")
    return sum(1 for base, worse in pairs if worse < base) / len(pairs)


def main() -> int:
    """Write the pair files for the ``test`` split (needs the GermanQuAD test download)."""
    cfg = load_config(REPO / "experiments/rq2/configs/rq2_judges.yaml")
    sources: dict[str, Sequence[QuadRow] | None] = {
        "correctness": load_germanquad(REPO / GERMANQUAD_TEST),
        "faithfulness_constructed": None,
    }
    for name in SETS:
        items = load_items(cfg.set_named(name), "test")
        rows = make_pairs(items, name, cfg.seed, quad_rows=sources[name])
        text = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
        (REPO / OUT[name]).write_text(text, encoding="utf-8")
        sys.stdout.write(f"{len(rows)} pairs -> {OUT[name]}\n")
    return 0


def load_pairs(root: Path = REPO) -> list[dict[str, object]]:
    """Read both pair files (one per licence), in ``SETS`` order.

    Raises:
        ConfigError: A pair file is missing (run ``make_degraded.py`` first).
    """
    rows: list[dict[str, object]] = []
    for name in SETS:
        path = root / OUT[name]
        if not path.is_file():
            msg = f"pair file {OUT[name]} is missing: run experiments/rq2/make_degraded.py"
            raise ConfigError(msg)
        rows += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return rows


if __name__ == "__main__":
    raise SystemExit(main())

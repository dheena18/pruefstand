"""Degraded answer pairs for the discrimination check (T5.4 S3).

From the ``test`` positives (top label) of ``correctness`` and ``faithfulness_constructed`` take
up to
50 answers per edit type that the T5.3 edits change: ``swap_first_number`` and ``negate``
(``rq2.construct``). Order: seeded permutation of the item ids, so the pairs are deterministic.
A judge discriminates when it scores the degraded answer strictly lower; it passes with
>= 90 % per edit type (D146 (3)). Only 21 ``correctness`` test positives admit ``negate``
(short annotator spans), so that cell has n = 21 (D932).

    uv run python experiments/rq2/make_degraded.py   # ->
    datasets/calibration/v1/degraded_pairs.jsonl
"""

import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run as a script: import rq2.*

from rq2.calib_schema import CalibrationItem, is_positive
from rq2.construct import negate, swap_first_number
from rq2.rq2_config import REPO, load_config, load_items

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


def make_pairs(
    items: Sequence[CalibrationItem],
    set_name: str,
    seed: int = 1234,
    per_edit: int = PAIRS_PER_EDIT,
) -> list[dict[str, object]]:
    """Return up to ``per_edit`` (base, degraded) pairs per edit type from top-label items.

    Args:
        items: One label set (only top-label items are used).
        set_name: Its name, written to every pair.
        seed: Seed of the order.
        per_edit: Pairs per edit type.

    Returns:
        Pair rows: ``pair_id, label_set, edit, base_item_id, cluster_id, metric, inputs, degraded``.
    """
    positives = sorted((i for i in items if is_positive(i)), key=lambda i: i.item_id)
    order = np.random.default_rng(seed).permutation(len(positives))
    pairs: list[dict[str, object]] = []
    for edit, fn in EDITS.items():
        taken = 0
        for idx in order:
            item = positives[int(idx)]
            changed = fn(item.inputs["antwort"])
            if changed is None or changed == item.inputs["antwort"] or taken >= per_edit:
                continue
            pairs.append(
                {
                    "pair_id": f"{item.item_id}:{edit}",
                    "label_set": set_name,
                    "edit": edit,
                    "base_item_id": item.item_id,
                    "cluster_id": item.cluster_id,
                    "metric": item.metric,
                    "inputs": item.inputs,
                    "degraded": {**item.inputs, "antwort": changed},
                }
            )
            taken += 1
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
    """Write the pair file for the ``test`` split."""
    cfg = load_config(REPO / "experiments/rq2/configs/rq2_judges.yaml")
    for name in SETS:
        rows = make_pairs(load_items(cfg.set_named(name), "test"), name, cfg.seed)
        text = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)
        (REPO / OUT[name]).write_text(text, encoding="utf-8")
        sys.stdout.write(f"{len(rows)} pairs -> {OUT[name]}\n")
    return 0


def load_pairs(root: Path = REPO) -> list[dict[str, object]]:
    """Read every pair file that exists (both licences), in ``SETS`` order."""
    rows: list[dict[str, object]] = []
    for name in SETS:
        path = root / OUT[name]
        if path.is_file():
            rows += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return rows


if __name__ == "__main__":
    raise SystemExit(main())

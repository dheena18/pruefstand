"""Drift anchors per pinned judge (T5.4 S9/S11; X3.4, D164, D253, D308).

Selects 50 seeded anchors from the ``test`` split of the publishable sets (never MEMERAG; incl.
``legal_hard`` once built), stratified by metric and label, half of them hard negatives. Each anchor
is judged at production concurrency (4) with the cache bypassed: ``--majority`` (default 5) runs
whose majority verdict is stored (T5.4d, D1250; ``--majority 1`` = the first run, T5.4), then
``--repeats`` (>= 4) further runs that give the flip rate f against it, its Wilson upper bound and
the judge's drift threshold (smallest c with P(Bin(50, f_upper) >= c) <= 1 %). ``--screen`` takes
the ``anchor_flips.json`` of an earlier run and replaces its unstable anchors (modal share < 0.8,
``judges.drift.unstable_anchors``) by seeded spares of the same stratum. Writes
``packages/pruefstand/src/pruefstand/judges/data/anchors/<model-slug>.jsonl`` and
``results/rq2/anchor_flips.json``.

    pruefstand-lock uv run python experiments/rq2/anchors.py --majority 5 --repeats 4
    # T5.4d second pass: add --screen results/rq2/anchor_flips_screen.json
"""

import argparse
import asyncio
import json
import sys
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run as a script: import rq2.*

from rq2.calib_schema import CalibrationItem, is_positive
from rq2.flips import flip_summary, judge_anchor_runs
from rq2.rq2_config import REPO, RQ2Config, load_config, load_items, set_available

from pruefstand.core.models.llm import Message
from pruefstand.judges.anchors import AnchorItem, anchor_file, load_anchors
from pruefstand.judges.drift import majority_scores, unstable_anchors
from pruefstand.judges.escaping import make_nonce, wrap
from pruefstand.judges.factory import PROMPT_ROOT
from pruefstand.judges.output import make_task
from pruefstand.llm.prompts import PromptRegistry

N_ANCHORS = 50
QUOTA = {
    "faithfulness": 14,
    "answer_correctness": 14,
    "refusal_judged": 11,
    "perturbation_consistency": 11,
}
HARD = {
    "faithfulness": 7,
    "answer_correctness": 7,
    "refusal_judged": 6,
    "perturbation_consistency": 5,
}
ANCHOR_NONCE = (
    b"rq2-anchor-public-nonce"  # public: the rendered prompts are stored in the repo anyway
)


def _pick(
    pool: Sequence[tuple[str, CalibrationItem]],
    k: int,
    rng: np.random.Generator,
    exclude: Collection[str] = (),
    spare_rng: np.random.Generator | None = None,
) -> list[tuple[str, CalibrationItem]]:
    """Seeded pick of ``k``; an excluded pick is replaced in place by a seeded spare (T5.4d)."""
    if len(pool) < k:
        msg = f"need {k} anchors, the pool has {len(pool)}"
        raise ValueError(msg)
    ordered = sorted(pool, key=lambda p: p[1].item_id)
    picked = [ordered[int(i)] for i in sorted(rng.choice(len(ordered), size=k, replace=False))]
    if not any(p[1].item_id in exclude for p in picked):
        return picked
    taken = {p[1].item_id for p in picked} | set(exclude)
    spare = [p for p in ordered if p[1].item_id not in taken]
    gen = spare_rng if spare_rng is not None else np.random.default_rng(0)
    spares = [spare[int(i)] for i in gen.permutation(len(spare))]
    if len(spares) < sum(1 for p in picked if p[1].item_id in exclude):
        msg = "not enough spare anchors to replace the excluded ones"
        raise ValueError(msg)
    return [spares.pop(0) if p[1].item_id in exclude else p for p in picked]


def select_anchors(
    sets: Mapping[str, Sequence[CalibrationItem]],
    seed: int = 1234,
    exclude: Collection[str] = (),
) -> list[tuple[str, CalibrationItem]]:
    """Pick the 50 anchors: per metric ``QUOTA``, of which ``HARD`` hard negatives, rest positives.

    ``exclude`` (item ids of unstable anchors, T5.4d) replaces each such pick in place by a spare of
    the same metric and stratum, drawn with ``seed + 1``; every other anchor stays as it was.

    Raises:
        ValueError: A MEMERAG item is offered, or a pool is too small.
    """
    rng = np.random.default_rng(seed)
    spare_rng = np.random.default_rng(seed + 1)
    picked: list[tuple[str, CalibrationItem]] = []
    for metric, quota in QUOTA.items():
        pool = [(name, i) for name, items in sets.items() for i in items if i.metric == metric]
        if any(i.source == "memerag" or "memerag" in name for name, i in pool):
            msg = "MEMERAG items are never anchors (they may go to GitHub Models)"
            raise ValueError(msg)
        hard = [p for p in pool if p[1].hard_negative]
        positive = [p for p in pool if is_positive(p[1]) and not p[1].hard_negative]
        picked += _pick(hard, HARD[metric], rng, exclude, spare_rng)
        picked += _pick(positive, quota - HARD[metric], rng, exclude, spare_rng)
    return picked


def screened_out(screen: Path, judge: str) -> list[str]:
    """Item ids of the unstable anchors of a screening run (T5.4d, D1250).

    ``screen`` is the ``anchor_flips.json`` of that run; its ``runs`` are in the order of the
    judge's current anchor file, which the same run wrote (checked via the stored verdicts).

    Raises:
        ValueError: The screen file and the anchor file do not belong to the same run.
    """
    summary = json.loads(screen.read_text(encoding="utf-8"))
    rows = load_anchors(anchor_file(judge))
    if summary.get("stored") != [r.raw_score for r in rows]:
        msg = f"{screen.name} does not match the anchor file of {judge}"
        raise ValueError(msg)
    return [rows[k].item_id for k in unstable_anchors(summary["runs"])]


def render(item: CalibrationItem, registry: PromptRegistry) -> tuple[Message, ...]:
    """Render the judge prompt of ``item`` exactly as ``Judge.score`` does (fixed public nonce)."""
    task = make_task(item.metric, **item.inputs)
    nonce = make_nonce(ANCHOR_NONCE, task.prompt_id, task.inputs)
    blocks = {name: wrap(name, text, nonce) for name, text in task.inputs.items()}
    return tuple(registry.get(task.prompt_id, task.prompt_version).render(**blocks))


def anchor_rows(
    picked: Sequence[tuple[str, CalibrationItem]],
    raw_scores: Sequence[int],
    judge: str,
    majority_runs: int = 1,
) -> list[AnchorItem]:
    """Build the anchor rows: rendered request plus the stored raw verdict (of how many runs)."""
    registry = PromptRegistry([PROMPT_ROOT])
    rows = []
    for k, ((name, item), raw) in enumerate(zip(picked, raw_scores, strict=True)):
        task = make_task(item.metric, **item.inputs)
        rows.append(
            AnchorItem(
                anchor_id=f"a{k:02d}",
                item_id=item.item_id,
                label_set=name,
                metric=item.metric,
                label=item.label,
                hard_negative=item.hard_negative,
                judge_model=judge,
                prompt_id=task.prompt_id,
                prompt_version=task.prompt_version,
                messages=render(item, registry),
                raw_score=raw,
                majority_runs=majority_runs,
            )
        )
    return rows


def publishable_sets(cfg: RQ2Config) -> dict[str, list[CalibrationItem]]:
    """The ``test`` items of every available set that may leave the VM (no ``local_only``)."""
    return {
        s.name: load_items(s, "test") for s in cfg.sets if not s.local_only and set_available(s)
    }


def main(argv: list[str] | None = None) -> int:
    """Select, judge ``--majority`` + ``--repeats`` times, write anchors and flip summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--judge", default="ollama/gemma3:12b")
    parser.add_argument("--family", default="gemma")
    parser.add_argument("--repeats", type=int, default=4, help="runs counted for the flip rate")
    parser.add_argument("--majority", type=int, default=5, help="runs of the stored majority")
    parser.add_argument("--screen", type=Path, help="anchor_flips.json of a screening run")
    args = parser.parse_args(argv)
    if args.repeats < 4 or args.majority < 1:
        sys.stderr.write("--repeats must be >= 4 (AI13-07) and --majority >= 1\n")
        return 2
    cfg = load_config(REPO / "experiments/rq2/configs/rq2_judges.yaml")
    replaced = screened_out(args.screen, args.judge) if args.screen else []
    picked = select_anchors(publishable_sets(cfg), cfg.seed, replaced)
    draft = anchor_rows(picked, [0] * len(picked), args.judge)
    # --majority 1 = T5.4 (run 1 stored, repeats - 1 counted); k > 1 = T5.4d (k + repeats runs)
    total = args.repeats if args.majority == 1 else args.majority + args.repeats
    runs = asyncio.run(judge_anchor_runs(draft, total, args.judge, args.family))
    summary = flip_summary(runs, args.judge, args.majority)
    summary["item_ids"] = [i.item_id for _, i in picked]
    summary["replaced"] = replaced
    rows = anchor_rows(picked, majority_scores(runs[: args.majority]), args.judge, args.majority)
    path = anchor_file(args.judge)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(r.model_dump_json() + "\n" for r in rows), encoding="utf-8")
    out = REPO / "results/rq2/anchor_flips.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sys.stdout.write(json.dumps(summary, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""RQ2 report (T5.4 S7/S8): tables, figure, committed inputs and ``calibration_status.yaml``.

``uv run python experiments/rq2/report.py`` reads the ``test`` verdicts of every judge
(``<out_dir>/verdicts_<slug>_test.parquet``), the pairs, bias and anchor results and writes
``results/rq2/{calibration,agreement_matrix,bias,discrimination}.csv``,
``results/rq2/cost_vs_kappa.png``,
``results/_inputs/rq2/verdicts.parquet`` (no text, no MEMERAG) and the status file. MEMERAG
verdicts go
to the git-ignored ``data/derived/memerag_de/verdicts.parquet``; without them (hosted runner) the
MEMERAG
rows of the existing ``calibration.csv`` are kept, and ``FROM_SCRATCH=1`` requires them.
"""

import json
import os
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run as a script: import rq2.*

from rq2.pass_rule import Outcome, metric_outcome, pass_rule_items, refusal_outcome
from rq2.report_figure import cost_vs_kappa
from rq2.report_tables import (
    agreement_matrix,
    cost_columns,
    discrimination_table,
    evidence,
    label_frame,
)
from rq2.rq2_config import REPO, RQ2Config, load_config, load_items, set_available, slug
from rq2.status_file import epoch_of, read_document, write_document

from pruefstand.judges.calibration import calibration_table
from pruefstand.judges.output import SPECS

RESULTS = REPO / "results/rq2"
INPUTS = REPO / "results/_inputs/rq2/verdicts.parquet"
MEMERAG_VERDICTS = REPO / "data/derived/memerag_de/verdicts.parquet"
#: Prompt versions tried per metric: dev (prompt work, AI13-12) and test (pass rule, once each).
PROMPT_VERSIONS_TRIED = {
    "faithfulness": {"dev": ["v2", "v3", "v4"], "test": ["v3", "v2"]},
    "answer_correctness": {"dev": ["v3", "v4"], "test": ["v4"]},
    "refusal_judged": {"dev": ["v1"], "test": ["v1"]},
    "perturbation_consistency": {"dev": ["v1"], "test": ["v1"]},
}


def _labels(cfg: RQ2Config) -> pl.DataFrame:
    items = []
    for entry in cfg.sets:
        if set_available(entry):
            items += [
                (entry.name, entry.origin, i) for i in pass_rule_items(load_items(entry, "test"))
            ]
    return label_frame(items)


def _verdicts(cfg: RQ2Config) -> tuple[pl.DataFrame, dict[str, dict[str, float | None]]]:
    frames, costs = [], {}
    out = REPO / cfg.out_dir
    for judge in cfg.judges:
        path = out / f"verdicts_{slug(judge.id)}_test.parquet"
        if path.is_file():
            frames.append(pl.read_parquet(path))
            calls = out / f"llm_calls_{slug(judge.id)}_test.parquet"
            if calls.is_file():
                costs[judge.id] = cost_columns(pl.read_parquet(calls), judge.id, cfg.concurrency)
    if not frames:
        msg = "no test verdicts found: run experiments/rq2/run_judges.py --split test first"
        raise SystemExit(msg)
    return pl.concat(frames), costs


def _pending_rows(cfg: RQ2Config, judges: list[str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for metric, sets in cfg.gating.items():
        for name in sets:
            if set_available(cfg.set_named(name)):
                continue
            for judge in judges:
                for stratum in ("all", "hard_negative"):
                    rows.append(
                        {
                            "judge": judge,
                            "metric": metric,
                            "label_set": name,
                            "stratum": stratum,
                            "label_origin": "construction",
                            "n": 0,
                            "evaluated": False,
                        }
                    )
    return rows


def _table(
    cfg: RQ2Config,
    labels: pl.DataFrame,
    verdicts: pl.DataFrame,
    costs: dict[str, dict[str, float | None]],
    disc: pl.DataFrame,
) -> pl.DataFrame:
    with_cost = (
        verdicts.with_columns(
            pl.col("judge")
            .replace_strict({j: c.get(k) for j, c in costs.items()}, default=None)
            .alias(k)
            for k in (
                "usd_per_1k",
                "gpu_s_per_1k",
                "quota_requests_per_1k",
                "latency_p50_ms",
                "latency_p95_ms",
            )
        )
        if costs
        else verdicts
    )
    table = calibration_table(labels, with_cost).drop("discrimination")
    keys = ["judge", "metric", "label_set"]
    worst = disc.group_by(keys).agg(pl.col("discrimination").min())
    table = table.join(worst, on=keys, how="left").with_columns(
        pl.lit(value=True).alias("evaluated")
    )
    pending = pl.DataFrame(
        _pending_rows(cfg, sorted(table["judge"].unique().to_list())), infer_schema_length=None
    )
    return pl.concat([table, pending], how="diagonal_relaxed") if pending.height else table


def _keep_memerag(table: pl.DataFrame) -> pl.DataFrame:
    old = RESULTS / "calibration.csv"
    if "memerag" in table["label_set"].to_list() or not old.is_file():
        return table
    if os.environ.get("FROM_SCRATCH") == "1":
        msg = "FROM_SCRATCH=1 needs the MEMERAG set under data/derived/memerag_de/"
        raise SystemExit(msg)
    kept = pl.read_csv(old, infer_schema_length=None).filter(pl.col("label_set") == "memerag")
    return pl.concat([table, kept], how="diagonal_relaxed")


def status_document(
    cfg: RQ2Config,
    table: pl.DataFrame,
    disc: pl.DataFrame,
    labels: pl.DataFrame,
    verdicts: pl.DataFrame,
) -> dict[str, object]:
    """Build ``calibration_status.yaml`` for the pinned (arm a) judge."""
    judge = next(j.id for j in cfg.judges if j.arm == "a")
    metrics: dict[str, object] = {}
    outcomes: list[Outcome] = []
    for metric, sets in cfg.gating.items():
        ev = {s: e for s in sets if (e := evidence(table, judge, metric, s)) is not None}
        d = disc.filter((pl.col("judge") == judge) & (pl.col("metric") == metric))
        out = metric_outcome(
            ev, sets, dict(zip(d["edit"].to_list(), d["discrimination"].to_list(), strict=True))
        )
        outcomes.append(out)
        metrics[metric] = {"status": out.status, "passed": out.passed, "reasons": list(out.reasons)}
    refusal_entry = _refusal_entry(cfg, labels, verdicts, judge)
    flips_path = RESULTS / "anchor_flips.json"
    flips = json.loads(flips_path.read_text(encoding="utf-8")) if flips_path.is_file() else {}
    doc = read_document()
    status = (
        "passed"
        if all(o.passed for o in outcomes)
        else ("failed" if any(o.status == "failed" for o in outcomes) else "pending")
    )
    from rq2.judge_serving import serving  # noqa: PLC0415

    return {
        "epoch": epoch_of(doc),
        "passed": status == "passed",
        "status": status,
        "refusal_judged": refusal_entry,
        "prompt_versions_tried": PROMPT_VERSIONS_TRIED,
        "prompt_versions": {m: f"{s.prompt_id}_{s.version}" for m, s in SPECS.items()},
        "judges": {
            judge: {
                "role": "gating, judge.pr and judge.nightly",
                "serving": serving(judge),
                "metrics": metrics,
                "drift_threshold": flips.get("drift_threshold"),
                "a0": flips.get("a0"),
                "flip_rate_upper": flips.get("flip_rate_upper"),
            }
        },
    }


def _refusal_entry(
    cfg: RQ2Config, labels: pl.DataFrame, verdicts: pl.DataFrame, judge: str
) -> dict[str, object]:
    """The ``refusal_judged`` block: the D193 outcome plus the measured numbers (D944)."""
    ref = labels.filter(pl.col("label_set") == "refusal").join(
        verdicts.filter(pl.col("judge") == judge).drop_nulls("score"), on=["item_id", "metric"]
    )
    items = load_items(cfg.set_named("refusal"), "test")
    near = sum(1 for i in items if i.construction.startswith("near_miss"))
    out = refusal_outcome(
        ref["label"].to_list(), ref["score"].to_list(), ref["hard_type"].to_list(), near_misses=near
    )
    y, p = ref["label"].to_numpy(), ref["score"].to_numpy()
    hedged = ref.filter(pl.col("hard_type") == "hedged_answer")["score"].to_numpy()
    reported = {
        "n": int(ref.height),
        "accuracy": float((y == p).mean()) if ref.height else None,
        "hedged_fpr": float(hedged.mean()) if hedged.size else None,
    }
    return {
        "passed": out.passed,
        "status": out.status,
        "reasons": list(out.reasons),
        "reported": reported,
    }


def evaluate_judge(judge: str) -> bool:
    """Re-run the pass rule for ``judge`` from its current test verdicts (``recalibrate.py``)."""
    cfg = load_config(REPO / "experiments/rq2/configs/rq2_judges.yaml")
    labels, (verdicts, costs) = _labels(cfg), _verdicts(cfg)
    disc = _discrimination(cfg)
    doc = status_document(cfg, _table(cfg, labels, verdicts, costs, disc), disc, labels, verdicts)
    return bool(doc["passed"]) and judge in doc["judges"]  # type: ignore[operator]  # mapping from the builder


def _discrimination(cfg: RQ2Config) -> pl.DataFrame:
    paths = [
        p for j in cfg.judges if (p := REPO / cfg.out_dir / f"pairs_{slug(j.id)}.parquet").is_file()
    ]
    if not paths:
        return pl.DataFrame(
            schema={
                "judge": pl.String,
                "label_set": pl.String,
                "metric": pl.String,
                "edit": pl.String,
                "n": pl.UInt32,
                "discrimination": pl.Float64,
                "base_top_share": pl.Float64,
            }
        )
    return discrimination_table(
        pl.concat([pl.read_parquet(p) for p in paths], how="diagonal_relaxed")
    )


def main() -> int:
    """Write every RQ2 output."""
    cfg = load_config(REPO / "experiments/rq2/configs/rq2_judges.yaml")
    labels, (verdicts, costs) = _labels(cfg), _verdicts(cfg)
    disc = _discrimination(cfg)
    table = _keep_memerag(_table(cfg, labels, verdicts, costs, disc))
    RESULTS.mkdir(parents=True, exist_ok=True)
    table.sort(["judge", "metric", "label_set", "stratum"]).write_csv(RESULTS / "calibration.csv")
    disc.write_csv(RESULTS / "discrimination.csv")
    agreement_matrix(verdicts).write_csv(RESULTS / "agreement_matrix.csv")
    from rq2.bias_report import bias_table  # noqa: PLC0415

    bias_table(cfg).write_csv(RESULTS / "bias.csv")
    cost_vs_kappa(table, RESULTS / "cost_vs_kappa.png")
    joined = verdicts.join(labels.select("item_id", "label"), on="item_id")
    is_memerag = pl.col("label_set") == "memerag"
    cols = ["item_id", "judge", "metric", "label_set", "label", "score"]
    INPUTS.parent.mkdir(parents=True, exist_ok=True)
    joined.filter(~is_memerag).select(cols).sort(cols[:2]).write_parquet(INPUTS)
    if joined.filter(is_memerag).height:
        joined.filter(is_memerag).select(cols).write_parquet(MEMERAG_VERDICTS)
    doc = status_document(cfg, table, disc, labels, verdicts)
    write_document(doc)
    sys.stdout.write(f"status: {doc['status']} refusal_judged: {doc['refusal_judged']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

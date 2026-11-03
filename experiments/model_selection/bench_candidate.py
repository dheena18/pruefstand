"""Candidate-model pass of the benchmark (T3.1b S6): one catalogue model at a time, under the lock.

The lead pulls and loads ONE candidate by the swap rule (ADR-0019); this module only measures it:
first-load time (cold when the model was not resident), German smoke (deterministic 0-2 score),
judge-JSON validity, throughput at concurrency 1 and 4, VRAM from the wrapper ``status`` and
``/api/ps`` and a provisional ``overhead_gib``. It never pulls, removes or swaps, and appends to
the day CSV with a ``run_id`` (answers go to their own file).

    make bench-models CANDIDATE=gemma3:4b    # pruefstand-lock ... bench_candidate --candidate ...
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from model_selection import bench, stats, vram
from model_selection import bench_runs as runs
from model_selection.bench_cases import CASES_PATH, load_cases
from model_selection.client import BenchError, OllamaClient, load_entry
from model_selection.vram import GIB, disk_bytes_of, overhead_gib

CANDIDATE_PHASES = ("quality", "json", "throughput")
MAX_OTHER_RESIDENT = 2
Row = dict[str, Any]


def check_candidate(
    tag: str, role: str, pulled: set[str], resident: set[str], *, lock_held: bool
) -> str | None:
    """Return the reason the pass must not start, else ``None``.

    Args:
        tag: Catalogue tag of the candidate.
        role: Catalogue role; embeddings and rerankers have their own bench (``embed_bench.py``).
        pulled: Tags of ``/api/tags`` (``:latest`` removed).
        resident: Tags of ``/api/ps`` (``:latest`` removed).
        lock_held: Whether ``PRUEFSTAND_LOCK_HELD=1``.
    """
    if not lock_held:
        return "run under the GPU lock: make bench-models CANDIDATE=<tag> (pruefstand-lock)"
    if role not in ("generator", "judge"):
        return f"{tag} has role {role}; embeddings and rerankers are measured by embed_bench.py"
    if tag not in pulled:
        return f"{tag} is not pulled on the cluster; pull it by the swap rule first (ADR-0019)"
    if len(resident - {tag}) > MAX_OTHER_RESIDENT:
        return f"resident set {sorted(resident)} has no room for {tag}; swap a model out first"
    return None


def tag_set(models: list[dict[str, Any]]) -> set[str]:
    """Tags of an ``/api/tags`` or ``/api/ps`` listing, ``:latest`` removed."""
    return {m["name"].removesuffix(":latest") for m in models}


def vram_row(client: OllamaClient, tag: str, disk: int, before: dict[str, int]) -> Row:
    """VRAM figures: wrapper ``status`` after (and delta to before), ``/api/ps``, overhead."""
    after = vram.snapshot()
    ps = runs.ps_entry(client, tag)
    size_vram = int(ps.get("size_vram", 0))
    row: Row = {
        "size_vram_gib": round(size_vram / GIB, 3),
        "disk_gib": round(disk / GIB, 3),
        "overhead_gib": overhead_gib(size_vram, disk),
        "overhead_provisional": 1,
        "context_length": ps.get("context_length", 0),
        "disk_free_gib": round(after.get("disk_models_free_kb", 0) / 1024**2, 2),
    }
    for key, used in after.items():
        if key.endswith("_used_mib"):
            row[key] = used
            row[f"{key}_delta"] = used - before.get(key, 0)
    return row


def quality_row(entry_id: str, answers: list[Row]) -> Row:
    """Summary row of the German smoke: mean score with the seeded 95 % bootstrap CI."""
    mean, lo, hi = stats.bootstrap_ci([a["score"] for a in answers], seed=42)
    return {
        "model": entry_id,
        "n": len(answers),
        "score_mean": round(mean, 3),
        "ci_lo": round(lo, 3),
        "ci_hi": round(hi, 3),
        "think_answers": sum("<think>" in a["answer"] for a in answers),
        "reloads": sum(a["load_s"] > runs.RELOAD_S for a in answers),
    }


def measure(tag: str, phases: list[str]) -> tuple[list[tuple[str, Row]], list[Row]]:
    """Run ``phases`` on the candidate; return (phase, row) pairs and the answer rows."""
    entry = load_entry(tag)
    client = OllamaClient(lane="GPU0" if entry.role == "generator" else "GPU1")
    pulled, resident = tag_set(client.get("tags")["models"]), tag_set(client.get("ps")["models"])
    lock_held = os.environ.get("PRUEFSTAND_LOCK_HELD") == "1"
    if (
        why := check_candidate(entry.tag, entry.role, pulled, resident, lock_held=lock_held)
    ) is not None:
        raise SystemExit(why)
    cases = load_cases(CASES_PATH)
    before, disk = vram.snapshot(), disk_bytes_of(tag)
    load_s = runs.warm_up(client, entry)  # cold load from the cluster disk if not resident
    load = {"model": entry.id, "first_load_s": round(load_s, 3)}
    rows: list[tuple[str, Row]] = [("load", {**load, "was_resident": int(entry.tag in resident)})]
    answers: list[Row] = []
    if "quality" in phases:
        answers = runs.quality_run(client, entry, cases)
        rows.append(("quality", quality_row(entry.id, answers)))
    if "json" in phases:
        rows.append(("json", runs.json_run(client, entry, cases)))
    if "throughput" in phases:
        pool = bench.long_pool(cases)
        for conc, calls in ((1, 3), (4, 8)):
            rows.append(("throughput", runs.throughput_run(client, entry, pool, conc, calls)))
    rows.append(("vram", {"model": entry.id, **vram_row(client, entry.tag, disk, before)}))
    return rows, answers


def write_candidate(
    out_dir: Path, day: str, tag: str, rows: list[tuple[str, Row]], answers: list[Row]
) -> str:
    """Append the rows to ``<day>.csv`` (phase prefix ``cand_``) under a fresh ``run_id``."""
    run_id = "cand-" + datetime.now().astimezone().strftime("%Y-%m-%dT%H%M")
    flat = [t for phase, row in rows for t in bench.flatten(run_id, day, f"cand_{phase}", row)]
    out_dir.mkdir(exist_ok=True)
    bench.write_outputs(out_dir, day, flat, [])
    if answers:
        slug = tag.replace(":", "-").replace("/", "_")
        text = "\n".join(json.dumps(a, ensure_ascii=False) for a in answers) + "\n"
        (out_dir / f"{day}_{slug}_answers.jsonl").write_text(stats.redact(text), encoding="utf-8")
    return run_id


def main(argv: list[str]) -> int:
    """Entry point; returns the process exit code."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidate", required=True, help="catalogue tag or id")
    ap.add_argument("--phases", default=",".join(CANDIDATE_PHASES))
    ap.add_argument("--date", default=datetime.now().astimezone().date().isoformat())
    ap.add_argument("--out-dir", type=Path, default=bench.RESULTS)
    args = ap.parse_args(argv)
    phases = [p for p in args.phases.split(",") if p]
    if unknown := sorted(set(phases) - set(CANDIDATE_PHASES)):
        ap.error(f"unknown phases {unknown}")
    try:
        rows, answers = measure(args.candidate, phases)
    except (BenchError, KeyError) as exc:
        print(f"candidate pass stopped: {exc!r}", file=sys.stderr)
        return 1
    print("run_id", write_candidate(args.out_dir, args.date, args.candidate, rows, answers))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

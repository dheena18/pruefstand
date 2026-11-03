"""T3.1b candidate pass and owner sheet: pure functions on real inputs (no network, no GPU)."""

import csv
import json
import subprocess
from pathlib import Path

import pytest
from model_selection import bench_candidate as cand
from model_selection import owner_sheet, vram
from model_selection.bench_cases import load_cases

REPO = Path(__file__).resolve().parents[3]
RESULTS = REPO / "experiments" / "model_selection" / "results"
ANSWERS = RESULTS / "2026-11-03_answers.jsonl"
SHEET = REPO / "experiments" / "model_selection" / "owner_score_10.csv"


def test_overhead_is_resident_minus_disk() -> None:
    gib = 1024**3
    assert vram.overhead_gib(11 * gib, 8 * gib) == pytest.approx(3.0)
    assert vram.overhead_gib(7 * gib, 8 * gib) == pytest.approx(-1.0)  # partial offload shows up


def test_disk_bytes_from_catalogue() -> None:
    assert vram.disk_bytes_of("gemma3:12b") == 8164039732
    assert vram.disk_bytes_of("ollama/gemma3:12b") == 8164039732
    with pytest.raises(KeyError):
        vram.disk_bytes_of("not-in-catalogue:1b")


def test_candidate_preconditions() -> None:
    ok = {"pulled": {"qwen3:4b", "gemma3:12b"}, "resident": {"gemma3:12b", "bge-m3"}}
    assert cand.check_candidate("qwen3:4b", "generator", **ok, lock_held=True) is None
    assert "GPU lock" in str(cand.check_candidate("qwen3:4b", "generator", **ok, lock_held=False))
    assert "not pulled" in str(cand.check_candidate("gemma3:4b", "judge", **ok, lock_held=True))
    assert "embed_bench" in str(cand.check_candidate("bge-m3", "embed", **ok, lock_held=True))
    crowded = {"pulled": {"qwen3:4b"}, "resident": {"a", "b", "c"}}
    assert "no room" in str(
        cand.check_candidate("qwen3:4b", "generator", **crowded, lock_held=True)
    )


def test_tag_set_drops_latest_suffix() -> None:
    models = [{"name": "bge-m3:latest"}, {"name": "gemma3:12b"}]
    assert cand.tag_set(models) == {"bge-m3", "gemma3:12b"}


def test_write_candidate_appends_with_run_id(tmp_path: Path) -> None:
    rows = [
        ("load", {"model": "ollama/x:1b", "first_load_s": 4.2}),
        ("throughput", {"model": "ollama/x:1b", "concurrency": 4, "n": 8}),
    ]
    answers = [{"model": "ollama/x:1b", "case": "lq01", "answer": "Ü", "score": 2, "load_s": 0.1}]
    first = cand.write_candidate(tmp_path, "2026-11-04", "x:1b", rows, answers)
    cand.write_candidate(tmp_path, "2026-11-04", "x:1b", rows, [])
    lines = list(csv.reader((tmp_path / "2026-11-04.csv").open(encoding="utf-8")))
    assert lines[0] == ["run_id", "date", "phase", "model", "concurrency", "metric", "value"]
    assert sum(r[0] == "run_id" for r in lines) == 1  # appended, header once
    assert first.startswith("cand-")
    assert {r[0] for r in lines[1:]} >= {first}
    assert lines[-1][2:] == ["cand_throughput", "ollama/x:1b", "4", "n", "8"]
    files = list(tmp_path.glob("2026-11-04_x-1b_cand-*_answers.jsonl"))
    assert len(files) == 1
    assert first in files[0].name
    text = files[0].read_text(encoding="utf-8")
    assert text.count("Ü") == 1
    assert json.loads(text)["run_id"] == first


def _make_dry_run(**variables: str) -> str:
    args = [f"{k}={v}" for k, v in variables.items()]
    done = subprocess.run(  # noqa: S603  # reason: fixed argv, no shell
        ["make", "-n", "-f", str(REPO / "mk" / "bench.mk"), "bench-models", *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout


def test_make_target_selects_the_candidate_pass_under_the_lock() -> None:
    day = _make_dry_run()
    assert "model_selection.bench --phases" in day
    assert "pruefstand-lock" in day
    one = _make_dry_run(CANDIDATE="gemma3:4b")
    assert 'model_selection.bench_candidate --candidate "gemma3:4b"' in one
    assert "pruefstand-lock" in one
    assert "model_selection.bench --phases" not in one


def test_owner_sheet_is_reproducible_and_spread_over_kinds() -> None:
    cases = load_cases()
    rows = [
        r
        for r in map(__import__("json").loads, ANSWERS.read_text(encoding="utf-8").splitlines())
        if r["model"] == owner_sheet.GENERATOR_ID
    ]
    first, again = owner_sheet.pick_items(rows), owner_sheet.pick_items(rows)
    assert first == again
    assert len(first) == 10
    assert len({r["case"] for r in first}) == 10
    assert {r["kind"] for r in first} == {c.kind for c in cases}  # every category at least once
    assert owner_sheet.pick_items(rows, seed=1) != first


def test_committed_owner_sheet_matches_the_picker_and_is_unscored(tmp_path: Path) -> None:
    out = tmp_path / "sheet.csv"
    assert owner_sheet.build(ANSWERS, out) == 10
    assert out.read_bytes() == SHEET.read_bytes()
    rows = list(csv.DictReader(SHEET.open(encoding="utf-8")))
    assert list(rows[0])[:3] == ["question", "answer", "score"]
    assert all(r["score"] == "" and r["question"] and r["answer"] for r in rows)


def test_eviction_of_a_day_set_model_is_detected() -> None:
    before = {"qwen3.8:27b-q8_0", "gemma3:12b"}
    assert cand.eviction(before, before | {"qwen3:4b"}, "qwen3:4b") is None
    why = cand.eviction(before, {"gemma3:12b", "qwen3:4b"}, "qwen3:4b")
    assert why is not None
    assert "qwen3.8:27b-q8_0" in why

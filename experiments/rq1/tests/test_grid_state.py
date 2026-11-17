"""T7.3 S5 (offline): resume and cleanup of the RQ1 grid cells."""

import json
from pathlib import Path

import pytest
from rq1.grid_state import (
    cell_status,
    cleanup_argv,
    collection_name,
    load_cells,
    resume_plan,
    summary,
)

from pruefstand.core.errors import ConfigError

# grid order on purpose NOT sorted, so a sorted() in resume_plan would show
HASHES = ["5795dfc18d0ed45f", "0047799c55b54988", "3e4db71fff8e7e64"]


def grid(tmp_path: Path) -> Path:
    rows = [{"name": f"c{i}", "rag_config_hash": h} for i, h in enumerate(HASHES)]
    (tmp_path / "grid.json").write_text(json.dumps({"seed": 1234, "cells": rows}), "utf-8")
    return tmp_path


def run(cell: Path, run_id: str, **manifest: object) -> None:
    (cell / run_id).mkdir(parents=True)
    (cell / run_id / "run.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_a_cell_is_done_only_with_a_complete_run_without_infra_error(tmp_path: Path) -> None:
    out = grid(tmp_path)
    assert cell_status(out / HASHES[0]) == "pending"
    run(out / HASHES[0], "r1", complete=False, infra_error="tunnel_lost: x")
    assert cell_status(out / HASHES[0]) == "partial"
    run(out / HASHES[0], "r2", complete=True, infra_error=None)
    assert cell_status(out / HASHES[0]) == "done"
    run(out / HASHES[1], "r1", complete=True, infra_error="ollama_down: x")  # not a valid finish
    assert cell_status(out / HASHES[1]) == "partial"
    (out / HASHES[2] / "bad").mkdir(parents=True)
    (out / HASHES[2] / "bad" / "run.json").write_text("{not json", encoding="utf-8")
    assert cell_status(out / HASHES[2]) == "partial"


def test_resume_skips_done_cells_and_cleanup_drops_only_theirs(tmp_path: Path) -> None:
    out = grid(tmp_path)
    run(out / HASHES[1], "r1", complete=True, infra_error=None)
    run(out / HASHES[2], "r1", complete=False, infra_error=None)
    assert resume_plan(out) == [HASHES[0], HASHES[2]]
    assert cleanup_argv(out) == [["uv", "run", "rag-demo", "index", "--drop", f"rq1_{HASHES[1]}"]]
    assert summary(out) == {"done": [HASHES[1]], "partial": [HASHES[2]], "pending": [HASHES[0]]}


def test_collection_names_are_rq1_scoped_and_checked() -> None:
    assert collection_name(HASHES[0]) == f"rq1_{HASHES[0]}"
    for bad in ("chunks_active", "pr_12_abc", "0047799C55B54988", ""):
        with pytest.raises(ConfigError, match="config hash"):
            collection_name(bad)


def test_a_missing_grid_json_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"run_grid\.py first"):
        load_cells(tmp_path)


def test_resume_keeps_the_grid_order(tmp_path: Path) -> None:
    out = grid(tmp_path)
    assert sorted(HASHES) != HASHES
    assert resume_plan(out) == HASHES


@pytest.mark.parametrize("flag", [1, "true", "True"])
def test_only_a_literal_true_marks_a_run_complete(tmp_path: Path, flag: object) -> None:
    out = grid(tmp_path)
    run(out / HASHES[0], "r1", complete=flag, infra_error=None)
    assert cell_status(out / HASHES[0]) == "partial"


@pytest.mark.parametrize("bad", ["../x", "../../etc", "0047799c55b5498/", "chunks_active"])
def test_grid_json_with_a_path_or_bad_hash_is_refused(tmp_path: Path, bad: str) -> None:
    rows = [{"name": "c0", "rag_config_hash": HASHES[0]}, {"name": "evil", "rag_config_hash": bad}]
    (tmp_path / "grid.json").write_text(json.dumps({"seed": 1, "cells": rows}), "utf-8")
    with pytest.raises(ConfigError, match="config hash"):
        load_cells(tmp_path)

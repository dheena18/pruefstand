"""T7.3: the RQ1 reranker choice is explicit (default first stage) and the per-cell run plan."""

import json
from pathlib import Path

import pytest
from rq1.grid import GRID, GridConfig
from rq1.grid_plan import main, write_plans
from rq1.run_grid import GPU_CONFIG, load_yaml, materialise, with_rerank, write_plan

BASE, GRID_YAML = load_yaml(GPU_CONFIG), load_yaml(GRID)


def test_the_default_is_first_stage_and_reranked_moves_every_hash() -> None:
    first = materialise(BASE, GRID_YAML)
    reranked = materialise(BASE, GRID_YAML, rerank="reranked")
    assert {c.config["rerank"]["on_retrieve"] for c in first} == {False}  # D1288, proposal A
    assert {c.config["rerank"]["on_retrieve"] for c in reranked} == {True}
    assert not {c.rag_hash for c in first} & {c.rag_hash for c in reranked}
    assert not {c.grid.config_hash for c in first} & {c.grid.config_hash for c in reranked}
    assert [c.grid.name for c in first] == [c.grid.name for c in reranked]


def test_grid_json_records_the_choice(tmp_path: Path) -> None:
    first = materialise(BASE, GRID_YAML)
    body = json.loads(write_plan(tmp_path / "a", first, 1234).read_text(encoding="utf-8"))
    assert body["rerank_mode"] == "first_stage"
    assert {row["rerank_on_retrieve"] for row in body["cells"]} == {False}
    reranked = materialise(BASE, GRID_YAML, rerank="reranked")
    path = write_plan(tmp_path / "b", reranked, 1234, "reranked")
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["rerank_mode"] == "reranked"
    assert {row["rerank_on_retrieve"] for row in body["cells"]} == {True}


def test_plans_cover_the_cells_still_to_run(tmp_path: Path) -> None:
    cells = materialise(BASE, GRID_YAML)
    write_plan(tmp_path, cells, 1234)
    done = cells[0].rag_hash
    (tmp_path / done / "r1").mkdir()
    run_json = '{"complete": true, "infra_error": null}'
    (tmp_path / done / "r1" / "run.json").write_text(run_json, "utf-8")
    plans = write_plans(tmp_path, Path("corpus/v1"), Path("pruefstand.yaml"))
    assert [p["cell"] for p in plans] == [c.rag_hash for c in cells[1:]]
    first = plans[0]
    assert first["collection"] == f"rq1_{first['cell']}"
    assert first["index_argv"][first["index_argv"].index("--collection") + 1] == first["collection"]
    assert first["run_argv"][first["run_argv"].index("--split") + 1] == "rq1"
    assert first["rerank_on_retrieve"] is False
    encoders = {p["index_argv"][p["index_argv"].index("--encoder") + 1] for p in plans}
    assert encoders == {"ollama", "tei"}
    assert (tmp_path / first["cell"] / "plan.json").is_file()
    assert not (tmp_path / done / "plan.json").exists()


def test_the_cli_prints_cleanup_only_for_done_cells(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cells = materialise(BASE, GRID_YAML)
    write_plan(tmp_path, cells, 1234)
    (tmp_path / cells[2].rag_hash / "r").mkdir()
    (tmp_path / cells[2].rag_hash / "r" / "run.json").write_text('{"complete": true}', "utf-8")
    assert main(["--out", str(tmp_path), "--corpus", "corpus/v1", "--cleanup"]) == 0
    assert capsys.readouterr().out.split() == [
        "uv", "run", "rag-demo", "index", "--drop", f"rq1_{cells[2].rag_hash}"
    ]  # fmt: skip


def test_no_plan_can_touch_the_shared_alias(tmp_path: Path) -> None:
    """Every cell indexes into its own rq1_<hash> collection, never chunks_active (gate index)."""
    cells = materialise(BASE, GRID_YAML)
    write_plan(tmp_path, cells, 1234)
    plans = write_plans(tmp_path, Path("corpus/v1"), Path("pruefstand.yaml"))
    assert len(plans) == len(cells)
    for plan in plans:
        index = plan["index_argv"]
        assert "--no-alias" in index, plan["cell"]
        assert index[index.index("--collection") + 1] == f"rq1_{plan['cell']}"
        assert plan["target_env"]["RAG_COLLECTION"] == f"rq1_{plan['cell']}"
        assert plan["target_env"]["RAG_CONFIG"].endswith(f"{plan['cell']}/rag.yaml")
        assert "chunks_active" not in " ".join(index + plan["run_argv"])


def test_the_rerank_override_is_a_deep_merge() -> None:
    reranked = materialise(BASE, GRID_YAML, rerank="reranked")
    for cell in reranked:
        assert cell.config["rerank"] == {**BASE["rerank"], "on_retrieve": True}
    cfg = GridConfig(
        name="x", config_hash="0" * 12, embedder="e", retrieval="dense", chunking="c",
        compound_split=None, overrides={"rerank": {"top_n": 5}},
    )  # fmt: skip
    assert with_rerank(cfg, "reranked").overrides["rerank"] == {"top_n": 5, "on_retrieve": True}

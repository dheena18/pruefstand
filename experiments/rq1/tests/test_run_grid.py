"""T7.3 S2 (offline): grid cells derived from rag.gpu.yaml (D1272), validated and written."""

import copy
import json
from pathlib import Path

import pytest
from rq1.grid import GRID, overrides_hash
from rq1.run_grid import (
    DERIVED,
    GPU_CONFIG,
    derived_grid,
    load_yaml,
    main,
    materialise,
    write_plan,
)

from pruefstand.core.errors import ConfigError

BASE = load_yaml(GPU_CONFIG)
GRID_YAML = load_yaml(GRID)


def test_the_bge_m3_arm_is_main_s_embed_section_and_never_the_tunnel() -> None:
    cells = materialise(BASE, GRID_YAML)
    assert len(cells) == 12
    for cell in cells:
        expected = (
            BASE["embed"]
            if cell.grid.embedder == DERIVED
            else GRID_YAML["embedders"][cell.grid.embedder]
        )
        assert cell.config["embed"] == expected
        assert cell.config["embed"]["endpoint_env"] != "OLLAMA_GPU0_URL"
    bge = [c for c in cells if c.grid.embedder == DERIVED]
    assert {c.config["embed"]["endpoint_env"] for c in bge} == {"LLM_PROXY_URL"}
    assert {c.config["embed"]["api_key_env"] for c in bge} == {"PRUEFSTAND_CANDIDATE_API_KEY"}


def test_cells_have_distinct_hashes_and_keep_the_rest_of_rag_gpu_yaml() -> None:
    cells = materialise(BASE, GRID_YAML)
    assert len({c.rag_hash for c in cells}) == len(cells)
    for cell in cells:
        assert cell.config["generator"] == BASE["generator"]
        assert cell.config["prompt_file"] == BASE["prompt_file"]
        assert cell.config["retrieval"]["hybrid"] is (cell.grid.retrieval == "hybrid")


def test_the_grid_hashes_cover_the_derived_section() -> None:
    before = {c.grid.name: c.grid.config_hash for c in materialise(BASE, GRID_YAML)}
    changed = copy.deepcopy(BASE)
    changed["embed"]["max_input_tokens"] = 512
    after = {c.grid.name: c.grid.config_hash for c in materialise(changed, GRID_YAML)}
    for name, value in before.items():
        assert (after[name] != value) is name.startswith(DERIVED), name


def test_a_tunnel_endpoint_is_refused() -> None:
    grid = copy.deepcopy(GRID_YAML)
    grid["embedders"]["e5_large_instruct"]["endpoint_env"] = "OLLAMA_GPU0_URL"
    with pytest.raises(ConfigError, match="would bypass llm-proxy"):
        materialise(BASE, grid)


def test_only_the_allowed_endpoint_variables_pass() -> None:
    grid = copy.deepcopy(GRID_YAML)
    grid["embedders"]["e5_large_instruct"]["endpoint_env"] = "SOME_OTHER_URL"
    with pytest.raises(ConfigError, match="not one of"):
        materialise(BASE, grid)


def test_two_cells_with_the_same_hash_are_refused() -> None:
    grid = copy.deepcopy(GRID_YAML)
    grid["embedders"]["twin"] = copy.deepcopy(BASE["embed"])  # the derived bge_m3 section again
    with pytest.raises(ConfigError, match="same rag-demo config hash"):
        materialise(BASE, grid)


def test_grid_json_carries_each_cell_s_grid_hash(tmp_path: Path) -> None:
    cells = materialise(BASE, GRID_YAML)
    rows = json.loads(write_plan(tmp_path, cells, 1234).read_text(encoding="utf-8"))["cells"]
    for row, cell in zip(rows, cells, strict=True):
        assert row["grid_hash"] == overrides_hash(cell.grid.overrides)
        assert row["rag_config_hash"] == cell.rag_hash
    assert len({row["grid_hash"] for row in rows}) == len(rows)


def test_derived_grid_does_not_change_its_inputs() -> None:
    grid = copy.deepcopy(GRID_YAML)
    derived_grid(grid, BASE)
    assert grid == GRID_YAML


def test_the_plan_is_written_per_cell_and_reproducible(tmp_path: Path) -> None:
    cells = materialise(BASE, GRID_YAML)
    first = write_plan(tmp_path / "a", cells, 1234).read_text(encoding="utf-8")
    second = write_plan(tmp_path / "b", cells, 1234).read_text(encoding="utf-8")
    assert first == second
    manifest = json.loads(first)
    assert manifest["seed"] == 1234
    assert [row["name"] for row in manifest["cells"]] == [c.grid.name for c in cells]
    for cell in cells:
        written = load_yaml(tmp_path / "a" / cell.rag_hash / "rag.yaml")
        assert written == cell.config


def test_the_cli_writes_twelve_cells(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--seed", "1234", "--out", str(tmp_path)]) == 0
    assert "12 cells" in capsys.readouterr().out
    assert len([p for p in tmp_path.iterdir() if p.is_dir()]) == 12

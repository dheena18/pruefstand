"""T7.1b (D1269): mutations M12-M20, precondition and data entries, pending entries."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from mutations.apply import GPU_CONFIG, apply_mutation, main
from mutations.gen_readme import render
from mutations.schema import (
    MUTATIONS_ROOT,
    MutationIndex,
    MutationSpec,
    load_all,
    load_index,
    load_spec,
)
from pydantic import ValidationError

REPO = MUTATIONS_ROOT.parents[1]
SPECS = load_all()
BY_ID = {spec.id: spec for spec in SPECS}


def _git(path: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout


def test_a_pending_entry_is_refused_by_the_cli(tmp_path: Path) -> None:
    root = tmp_path / "mutations"
    shutil.copytree(MUTATIONS_ROOT, root, ignore=shutil.ignore_patterns("__pycache__"))
    index = (root / "index.yaml").read_text(encoding="utf-8").replace("N03, N04, N05", "N03, N05")
    (root / "index.yaml").write_text(
        index + "pending:\n  N04: waits for a GPU re-record of its fixtures\n", encoding="utf-8"
    )
    assert load_index(root).pending == {"N04": "waits for a GPU re-record of its fixtures"}
    assert "## Pending" in render(root)
    assert main(["apply", "N04", "--worktree", str(tmp_path / "wt")], root=root) == 1
    assert not (tmp_path / "wt").exists()


def test_pending_and_entries_never_overlap() -> None:
    sha = "0" * 40
    with pytest.raises(ValidationError, match="overlap"):
        MutationIndex.model_validate(
            {"base_sha": sha, "entries": ["N04"], "pending": {"N04": "waits for a GPU re-record"}}
        )
    with pytest.raises(ValidationError, match="reason"):
        MutationIndex.model_validate({"base_sha": sha, "entries": ["N01"], "pending": {"N04": "x"}})


CATALOGUE = yaml.safe_load((REPO / "infra/gpu/models.yaml").read_text(encoding="utf-8"))["models"]


def test_m17_temperature_is_inside_the_generator_option_bounds() -> None:
    spec = BY_ID["M17"]
    assert spec.kind == "config"
    assert spec.rag_overrides == {"generation": {"temperature": 0.7}}
    gpu = yaml.safe_load((REPO / GPU_CONFIG).read_text(encoding="utf-8"))
    entry = next(m for m in CATALOGUE if m["id"] == gpu["generator"]["catalogue_id"])
    low, high = entry["option_bounds"]["temperature"]
    assert low <= 0.7 <= high
    assert spec.expected.status == "FAIL"


def test_t7_1b_strata_tiers_and_metrics() -> None:
    added = [BY_ID[f"M{i}"] for i in range(12, 21)]
    assert {s.id for s in added if s.stratum == "deterministic"} == {"M12", "M16"}
    assert {s.id for s in added if s.stratum == "normaliser"} == {"M20"}
    assert not any(s.tier1 for s in SPECS if s.stratum == "statistical")
    assert BY_ID["M13"].expected.metrics == ("ndcg_at_k",)
    for entry in ("M14", "M15"):
        assert BY_ID[entry].tier == "pr"
        assert BY_ID[entry].splits == ("core",)
        assert BY_ID[entry].expected.metrics == ("ndcg_at_k",)
    m20 = BY_ID["M20"]
    assert (m20.expected.status, m20.in_detection_rate, m20.splits) == ("PASS", False, ("core",))
    for entry in ("M04", "M14", "M16", "M18", "M19"):
        assert BY_ID[entry].needs_reindex


def test_m16_is_a_precondition_abort_in_both_tiers() -> None:
    m16 = BY_ID["M16"]
    assert (m16.kind, m16.data_ref, m16.tier1) == ("data", "previous", True)
    assert m16.expected.status == "FAIL"
    assert m16.expected.metrics == ()
    assert m16.expected.precondition == "corpus_mismatch"
    assert m16.expected.likely_cause is None
    with pytest.raises(ValidationError, match="precondition"):
        MutationSpec.model_validate(
            {
                **m16.model_dump(),
                "expected": {
                    "status": "FAIL",
                    "precondition": "corpus_mismatch",
                    "metrics": ["error_rate"],
                },
            }
        )


def test_m14_cuts_query_and_passage_inputs_and_leaves_normalisation_alone() -> None:
    patch = (MUTATIONS_ROOT / "M14" / "patch.diff").read_text(encoding="utf-8")
    added = [
        line for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++")
    ]
    assert "a/apps/rag-demo/src/rag_demo/index/encoders.py" in patch
    assert any("[:128]" in line for line in added)
    assert not any("normal" in line.lower() for line in added)


def test_pending_entries_validate_and_n09_invalidates_the_cache() -> None:
    m11, n09 = load_spec("M11"), load_spec("N09")
    assert m11.rag_overrides is not None
    assert "generator" in m11.rag_overrides
    assert n09.cache_invalidating
    assert n09.expected.status == "PASS"


def test_a_data_entry_changes_no_file(worktree: Path) -> None:
    head = _git(REPO, "rev-parse", "HEAD").strip()
    apply_mutation(BY_ID["M16"], worktree, head)
    assert _git(worktree, "status", "--porcelain") == ""


def test_data_ref_belongs_to_kind_data_only() -> None:
    m16 = BY_ID["M16"].model_dump()
    with pytest.raises(ValidationError, match="data_ref exactly for kind data"):
        MutationSpec.model_validate({**m16, "kind": "config"})
    m12 = BY_ID["M12"].model_dump()
    with pytest.raises(ValidationError, match="data_ref exactly for kind data"):
        MutationSpec.model_validate({**m12, "kind": "data"})

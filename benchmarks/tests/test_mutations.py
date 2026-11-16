"""T7.1a: mutation entries validate, are pre-registered (X3.10, P3.3) and apply/revert cleanly."""

import subprocess
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest
import yaml
from mutations.apply import (
    GPU_CONFIG,
    LIVE_CONFIG,
    MutationError,
    apply_mutation,
    check_canary_set,
    ensure_worktree,
    main,
    revert,
)
from mutations.gen_readme import render
from mutations.schema import (
    MUTATIONS_ROOT,
    MutationIndex,
    MutationSpec,
    load_all,
    load_index,
    load_spec,
)
from pydantic import BaseModel, ValidationError

from pruefstand.core.config_loader import load_config
from pruefstand.core.models.gate import CAUSE_MESSAGES
from pruefstand.metrics.registry import MetricRegistry
from rag_demo.models import RagConfig

REPO = MUTATIONS_ROOT.parents[1]
SPECS = load_all()
BY_ID = {spec.id: spec for spec in SPECS}
SLICE_1 = {"M01", "M04", "M05", "M06", "M07", "M08", "M09", "M10"} | {
    f"N0{i}" for i in (1, 2, 3, 5, 6, 7, 8)
}
NIGHTLY_ONLY = {"refusal_correct"}  # interfaces §5: gated in nightly `full` only (X3.7)
RETRIEVAL = {
    "context_recall",
    "ndcg_at_k",
}  # the only metrics with a perturbed_all pair (gate.slices)


def _gated_metrics() -> set[str]:
    return set(load_config(REPO / "pruefstand.yaml").gate.metrics)


def test_index_lists_exactly_the_folders_and_ids_are_unique() -> None:
    index = load_index()
    entries = index.entries
    assert len(entries) == len(set(entries))
    folders = {p.parent.name for p in MUTATIONS_ROOT.glob("*/mutation.yaml")}
    assert set(entries) | set(index.pending) == folders
    assert set(entries) == SLICE_1
    assert set(index.pending) == {"N04"}  # waits for the GPU re-record (D1261)


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.id)
def test_statistical_entries_are_pre_registered_in_their_tier(spec: MutationSpec) -> None:
    if spec.stratum != "statistical":
        return
    gated = _gated_metrics()
    for metric in spec.expected.metrics:
        assert metric in gated, f"{spec.id}: {metric} is not gated under pruefstand.yaml"
        if metric in NIGHTLY_ONLY:
            assert spec.tier == "nightly", f"{spec.id}: {metric} is gated in nightly runs only"
            assert spec.splits == ("full",)


def test_moving_m06_to_the_pr_tier_breaks_the_pre_registration() -> None:
    data = BY_ID["M06"].model_dump()
    with pytest.raises(ValidationError, match="tier pr"):
        MutationSpec.model_validate({**data, "tier": "pr"})
    moved = MutationSpec.model_validate({**data, "tier": "pr", "splits": ["core"]})
    assert moved.tier == "pr"
    assert NIGHTLY_ONLY & set(moved.expected.metrics)  # the parametrised check above rejects it


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.id)
def test_metrics_slices_and_causes_are_known(spec: MutationSpec) -> None:
    registry = set(MetricRegistry.default().directions())
    assert set(spec.expected.metrics) <= registry
    assert set(spec.expected.secondary_metrics) <= registry | {"evidence_recall"}
    if "perturbed_all" in spec.expected.gated_slices:
        assert set(spec.expected.metrics) <= RETRIEVAL
    assert spec.expected.likely_cause is None or spec.expected.likely_cause in CAUSE_MESSAGES
    if spec.expected.hard_fail:
        assert spec.expected.likely_cause is None


def test_p33_statistical_expect_fail_and_no_should_detect() -> None:
    for path in MUTATIONS_ROOT.glob("*/mutation.yaml"):
        text = path.read_text(encoding="utf-8")
        assert "should_detect" not in text
        assert "WARN or FAIL" not in text
    mutations = [s for s in SPECS if not s.is_noop]
    assert all(s.expected.status == "FAIL" for s in mutations if s.stratum == "statistical")
    with pytest.raises(ValidationError, match=r"P3\.3"):
        MutationSpec.model_validate(
            {
                **BY_ID["M10"].model_dump(),
                "expected": {"status": "WARN", "metrics": ["context_recall"]},
            }
        )


def test_tier1_only_for_hard_fail_entries() -> None:
    assert {s.id for s in SPECS if s.tier1} == {"M08", "M09"}
    assert not any(BY_ID[i].tier1 for i in ("M01", "M05", "M07", "M10"))


def _model_for(model: type[BaseModel], key: str) -> type[BaseModel] | None:
    annotation = model.model_fields[key].annotation
    candidates = getattr(annotation, "__args__", (annotation,))
    return next((c for c in candidates if isinstance(c, type) and issubclass(c, BaseModel)), None)


def _assert_keys_exist(model: type[BaseModel], overrides: Mapping[str, object]) -> None:
    for key, value in overrides.items():
        assert key in model.model_fields, f"{key} is not a field of {model.__name__}"
        if isinstance(value, Mapping):
            sub = _model_for(model, key)
            assert sub is not None, f"{key} is not a nested model"
            _assert_keys_exist(sub, value)


@pytest.mark.parametrize("spec", [s for s in SPECS if s.rag_overrides], ids=lambda s: s.id)
def test_rag_overrides_are_ragconfig_fields_and_the_result_validates(spec: MutationSpec) -> None:
    assert spec.rag_overrides is not None
    _assert_keys_exist(RagConfig, spec.rag_overrides)
    prompt = spec.rag_overrides.get("prompt_file")
    if isinstance(prompt, str):
        assert (REPO / "apps/rag-demo/src/rag_demo" / prompt).is_file()


def test_leak_mutations_refuse_the_published_canary_set() -> None:
    for entry in ("M08", "M09"):
        with pytest.raises(MutationError, match="leak"):
            check_canary_set(BY_ID[entry], "published", allow_published=False)
        check_canary_set(BY_ID[entry], "published", allow_published=True)
        check_canary_set(BY_ID[entry], "heldout", allow_published=False)
    check_canary_set(BY_ID["M10"], "published", allow_published=False)


@pytest.fixture
def worktree(tmp_path: Path) -> Iterator[Path]:
    path = tmp_path / "wt"
    yield path
    subprocess.run(  # noqa: S603
        ["git", "worktree", "remove", "--force", str(path)],  # noqa: S607
        cwd=REPO,
        check=False,
        capture_output=True,
        timeout=60,
    )


def _git(path: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout


def test_m08_changes_both_profiles_and_revert_leaves_a_clean_tree(worktree: Path) -> None:
    head = _git(REPO, "rev-parse", "HEAD").strip()
    apply_mutation(BY_ID["M08"], worktree, head)
    changed = set(_git(worktree, "diff", "--name-only").split())
    assert changed == {GPU_CONFIG, LIVE_CONFIG}
    numstat = _git(worktree, "diff", "--numstat").split()
    assert numstat[0::3] == ["1", "1"]  # one line per profile, comments kept
    for rel in changed:
        cfg = RagConfig.model_validate(yaml.safe_load((worktree / rel).read_text(encoding="utf-8")))
        assert cfg.tenant_filter == "post_topk"
    revert(worktree)
    assert _git(worktree, "status", "--porcelain") == ""


def test_tier2_only_entry_changes_only_the_gpu_profile(worktree: Path) -> None:
    head = _git(REPO, "rev-parse", "HEAD").strip()
    apply_mutation(BY_ID["M04"], worktree, head)
    assert _git(worktree, "diff", "--name-only").split() == [GPU_CONFIG]
    revert(worktree)
    assert _git(worktree, "status", "--porcelain") == ""


def test_refuses_a_checkout_it_did_not_create(tmp_path: Path) -> None:
    with pytest.raises(MutationError, match=r"not created by apply\.py"):
        ensure_worktree(REPO, "HEAD")
    with pytest.raises(MutationError, match=r"not created by apply\.py"):
        revert(REPO)
    with pytest.raises(MutationError, match=r"not created by apply\.py"):
        ensure_worktree(tmp_path, "HEAD")


def test_a_second_apply_on_a_mutated_worktree_is_refused(worktree: Path) -> None:
    # Review of #182: M08 then M05 on the same worktree stacked both mutations.
    head = _git(REPO, "rev-parse", "HEAD").strip()
    apply_mutation(BY_ID["M08"], worktree, head)
    with pytest.raises(MutationError, match="not clean"):
        apply_mutation(BY_ID["M05"], worktree, head)
    assert "answer_no_citations" not in (worktree / GPU_CONFIG).read_text(encoding="utf-8")
    revert(worktree)
    apply_mutation(BY_ID["M05"], worktree, head)  # clean again: allowed
    assert "post_topk" not in (worktree / GPU_CONFIG).read_text(encoding="utf-8")


def test_an_apply_on_a_worktree_that_left_the_base_is_refused(worktree: Path) -> None:
    # Review of #182: after HEAD moved, an apply ran on the wrong base.
    head = _git(REPO, "rev-parse", "HEAD").strip()
    apply_mutation(BY_ID["M10"], worktree, head)
    revert(worktree)
    _git(worktree, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "commit", "--quiet", "--allow-empty", "--no-verify", "-m", "moved")  # fmt: skip
    with pytest.raises(MutationError, match="not at the base"):
        apply_mutation(BY_ID["M10"], worktree, head)
    assert _git(worktree, "status", "--porcelain") == ""


PATCHED = [s for s in SPECS if s.patch is not None]


@pytest.mark.parametrize("spec", PATCHED, ids=lambda s: s.id)
def test_every_patch_applies_to_the_current_tree(spec: MutationSpec) -> None:
    assert spec.patch is not None
    _git(REPO, "apply", "--check", str(MUTATIONS_ROOT / spec.id / spec.patch))


def test_no_ops_change_nothing_that_parses_differently(worktree: Path) -> None:
    head = _git(REPO, "rev-parse", "HEAD").strip()
    gpu = (REPO / GPU_CONFIG).read_text(encoding="utf-8")
    for entry in ("N01", "N05"):
        apply_mutation(BY_ID[entry], worktree, head)
        changed = (worktree / GPU_CONFIG).read_text(encoding="utf-8")
        assert changed != gpu
        assert yaml.safe_load(changed) == yaml.safe_load(gpu)
        revert(worktree)


def test_a_patch_entry_with_a_new_file_reverts_to_a_clean_tree(worktree: Path) -> None:
    head = _git(REPO, "rev-parse", "HEAD").strip()
    apply_mutation(load_spec("N04"), worktree, head)
    prompt = worktree / "apps/rag-demo/src/rag_demo/prompts/answer_de_v3.txt"
    assert "Antworte auf die Frage" in prompt.read_text(encoding="utf-8")
    revert(worktree)
    assert not prompt.exists()
    assert _git(worktree, "status", "--porcelain") == ""


def test_n03_changes_nothing(worktree: Path) -> None:
    head = _git(REPO, "rev-parse", "HEAD").strip()
    apply_mutation(BY_ID["N03"], worktree, head)
    assert _git(worktree, "status", "--porcelain") == ""


def test_no_ops_expect_pass_and_stay_out_of_the_detection_rate() -> None:
    for spec in (s for s in SPECS if s.is_noop):
        assert spec.expected.status == "PASS"
        assert not spec.in_detection_rate
        assert not spec.tier1
    with pytest.raises(ValidationError, match="no-op expects PASS"):
        MutationSpec.model_validate({**BY_ID["N01"].model_dump(), "expected": {"status": "FAIL"}})


def test_the_readme_is_generated_from_the_yaml() -> None:
    readme = (MUTATIONS_ROOT / "README.md").read_text(encoding="utf-8")
    assert readme == render()
    assert "| Stratum | tier1 |" in readme


def test_a_pending_entry_is_refused_by_the_cli_and_listed_in_the_readme(tmp_path: Path) -> None:
    assert main(["apply", "N04", "--worktree", str(tmp_path / "wt")]) == 1
    assert not (tmp_path / "wt").exists()
    assert "- `N04`: The new prompt version" in (MUTATIONS_ROOT / "README.md").read_text("utf-8")


def test_pending_and_entries_never_overlap() -> None:
    sha = "0" * 40
    with pytest.raises(ValidationError, match="overlap"):
        MutationIndex.model_validate(
            {"base_sha": sha, "entries": ["N04"], "pending": {"N04": "waits for a GPU re-record"}}
        )
    with pytest.raises(ValidationError, match="reason"):
        MutationIndex.model_validate({"base_sha": sha, "entries": ["N01"], "pending": {"N04": "x"}})

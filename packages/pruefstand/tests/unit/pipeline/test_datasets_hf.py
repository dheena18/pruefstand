"""``hf://<user>/<name>@<tag>``: snapshot_download into a cache, then a local load (T4.7b S6).

No network: ``snapshot_download`` is replaced by a function that copies a local export layout.
"""

import json
import os
import shutil
from pathlib import Path

import pytest
from testsupport.pipeline_support import case_rows, write_dataset
from testsupport.run_builders import make_cases

from pruefstand.core.enums import Split
from pruefstand.core.errors import ConfigError, DatasetError
from pruefstand.dataset.export_hf import build_hf_layout
from pruefstand.pipeline import datasets_hf
from pruefstand.pipeline.datasets import check_dataset, load_cases

REF = "hf://someone/pruefstand-de@v1"


class FakeHub:
    """Records the calls and plays back a prepared snapshot directory."""

    def __init__(self, snapshot: Path) -> None:
        self.snapshot = snapshot
        self.calls: list[dict[str, object]] = []

    def __call__(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        target = Path(str(kwargs["local_dir"]))
        shutil.copytree(self.snapshot, target, dirs_exist_ok=True, symlinks=True)
        (target / ".cache" / "huggingface").mkdir(parents=True, exist_ok=True)
        return str(target)


@pytest.fixture
def hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeHub:
    cases = make_cases(4, split="core")
    source = write_dataset(
        tmp_path / "src",
        {"core": case_rows(cases), "smoke": case_rows(make_cases(5, split="smoke")[4:])},
    )
    layout = tmp_path / "hf_export"
    build_hf_layout(source, layout)
    fake = FakeHub(layout)
    monkeypatch.setattr(datasets_hf, "snapshot_download", fake)
    monkeypatch.setattr(datasets_hf, "CACHE_ROOT", tmp_path / "cache")
    return fake


def test_an_hf_reference_loads_like_a_local_directory(hub: FakeHub) -> None:
    name, version, cases = load_cases(REF, (Split.CORE,))
    assert (name, version) == ("tmpset", "v1")
    assert len(cases) == 4
    assert hub.calls[0]["repo_id"] == "someone/pruefstand-de"
    assert hub.calls[0]["revision"] == "v1"
    assert hub.calls[0]["repo_type"] == "dataset"


def test_a_second_call_uses_the_cache(hub: FakeHub) -> None:
    load_cases(REF, (Split.CORE,))
    load_cases(REF, (Split.CORE, Split.SMOKE))
    assert len(hub.calls) == 1


def test_a_moving_revision_is_downloaded_again(hub: FakeHub) -> None:
    load_cases("hf://someone/pruefstand-de@main", (Split.CORE,))
    load_cases("hf://someone/pruefstand-de@main", (Split.CORE,))
    assert len(hub.calls) == 2


def test_check_dataset_loads_every_split_of_the_manifest(hub: FakeHub) -> None:
    loaded = check_dataset(REF)
    assert {c.split for c in loaded.cases} == {Split.CORE, Split.SMOKE}


@pytest.mark.parametrize(
    "ref", ["hf://x", "hf://a/b/c@v1", "hf://a/b@", "hf://../b@v1", "hf://a/b@../x", "hf:///b@v1"]
)
def test_malformed_references_are_config_errors(ref: str) -> None:
    with pytest.raises(ConfigError, match=r"hf://"):
        load_cases(ref, (Split.CORE,))


def test_a_snapshot_without_a_manifest_is_a_dataset_error(hub: FakeHub, tmp_path: Path) -> None:
    (hub.snapshot / "dataset_manifest.json").unlink()
    with pytest.raises(DatasetError, match=r"dataset_manifest\.json"):
        load_cases(REF, (Split.CORE,))


def test_a_row_that_disagrees_with_the_manifest_is_refused(hub: FakeHub) -> None:
    path = hub.snapshot / "laws_eurlex" / "core.jsonl"
    path.write_text(path.read_text("utf-8").splitlines()[0] + "\n", encoding="utf-8")
    with pytest.raises(DatasetError, match=r"but dataset_manifest\.json says 4"):
        load_cases(REF, (Split.CORE,))


def test_a_failed_download_is_a_dataset_error_naming_the_ref(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def broken(**_: object) -> str:
        msg = "offline"
        raise OSError(msg)

    monkeypatch.setattr(datasets_hf, "snapshot_download", broken)
    monkeypatch.setattr(datasets_hf, "CACHE_ROOT", tmp_path / "cache")
    with pytest.raises(DatasetError, match="someone/pruefstand-de@v1"):
        load_cases(REF, (Split.CORE,))


def test_the_manifest_survives_the_export_round_trip(hub: FakeHub) -> None:
    exported = json.loads((hub.snapshot / "dataset_manifest.json").read_text("utf-8"))
    assert exported["name"] == "tmpset"


def test_a_symlinked_split_file_in_the_snapshot_is_refused(hub: FakeHub, tmp_path: Path) -> None:
    outside = tmp_path / "outside.jsonl"
    outside.write_text("{}\n", encoding="utf-8")
    link = hub.snapshot / "laws_eurlex" / "smoke.jsonl"
    link.unlink(missing_ok=True)
    link.symlink_to(outside)
    with pytest.raises(DatasetError, match="regular file"):
        load_cases(REF, (Split.CORE,))


@pytest.mark.network
def test_the_real_hub_resolves_a_public_dataset_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Needs the internet and a published repo; the owner sets ``PRUEFSTAND_HF_TEST_REF``."""
    ref = os.environ.get("PRUEFSTAND_HF_TEST_REF")
    if not ref:
        pytest.skip("PRUEFSTAND_HF_TEST_REF (hf://<user>/<name>@<tag>) is not set")
    monkeypatch.setattr(datasets_hf, "CACHE_ROOT", tmp_path / "cache")
    assert check_dataset(ref).cases


def _hub_with_heldout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tags_of: dict[int, tuple[str, ...]]
) -> FakeHub:
    cases = [
        c.model_copy(update={"tags": tags_of.get(i, ())})
        for i, c in enumerate(make_cases(4, split="core"))
    ]
    smoke = make_cases(5, split="smoke")[4:]
    source = write_dataset(tmp_path / "src", {"core": case_rows(cases), "smoke": case_rows(smoke)})
    layout = tmp_path / "hf_export"
    build_hf_layout(source, layout)
    fake = FakeHub(layout)
    monkeypatch.setattr(datasets_hf, "snapshot_download", fake)
    monkeypatch.setattr(datasets_hf, "CACHE_ROOT", tmp_path / "cache")
    return fake


def test_a_heldout_case_is_not_exported_and_the_counts_follow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _hub_with_heldout(tmp_path, monkeypatch, {1: ("heldout",)})
    _, _, cases = load_cases(REF, (Split.CORE,))
    assert len(cases) == 3


def test_a_fully_filtered_split_leaves_the_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _hub_with_heldout(tmp_path, monkeypatch, {})
    all_private: dict[int, tuple[str, ...]] = dict.fromkeys(range(4), ("private",))
    hub = _hub_with_heldout(tmp_path / "again", monkeypatch, all_private)
    manifest = json.loads((hub.snapshot / "dataset_manifest.json").read_text("utf-8"))
    assert manifest["splits"] == {"smoke": 1}
    assert {c.split for c in check_dataset(REF).cases} == {Split.SMOKE}

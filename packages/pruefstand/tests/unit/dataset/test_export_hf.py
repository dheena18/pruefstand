"""``export_hf``: HF layout per licence config, dataset card, dry run, private data (T4.1 S5)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
import respx
import yaml
from testsupport.dataset_support import CORPUS, case

from pruefstand.core.enums import Split
from pruefstand.core.errors import ConfigError, DatasetError
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset import export_hf as module
from pruefstand.dataset.export_hf import export_hf
from pruefstand.dataset.io import build_manifest, write_dataset

SPLITS = (Split.SMOKE, Split.CORE, Split.ROBUST_PR, Split.FULL)
ROOT = Path(__file__).resolve().parents[5]


def _cases() -> list[TestCase]:
    out: list[TestCase] = []
    for i, split in enumerate(SPLITS):
        for config in ("laws_eurlex", "germanquad_derived"):
            out.append(
                case(
                    f"{split.value}-{config}", f"d{i}-{config}", split=split, license_config=config
                )
            )
    out.append(case("own-1", "own-doc", split=Split.CORE, license_config="own"))
    return out


def _dataset(directory: Path) -> Path:
    cases = _cases()
    write_dataset(directory, cases, build_manifest("pruefstand-de", "v1", CORPUS, cases, seed=0))
    return directory


def _front_matter(readme: Path) -> dict[str, object]:
    text = readme.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    loaded = yaml.safe_load(text.split("---\n")[1])
    assert isinstance(loaded, dict)
    return loaded


def test_dry_run_builds_the_layout_without_network(tmp_path: Path) -> None:
    directory = _dataset(tmp_path / "d")
    with respx.mock(assert_all_called=False) as router:
        export_hf(directory, "u/r", private=True, dry_run=True)
        assert len(router.calls) == 0
    out = directory / "hf_export"
    for config in ("laws_eurlex", "germanquad_derived"):
        for split in SPLITS:
            assert (out / config / f"{split.value}.jsonl").is_file()
    assert (out / "own" / "core.jsonl").is_file()
    assert not (out / "own" / "smoke.jsonl").exists()
    card = _front_matter(out / "README.md")
    configs = card["configs"]
    assert isinstance(configs, list)
    assert {c["config_name"] for c in configs} == {"laws_eurlex", "germanquad_derived", "own"}
    licenses = card["config_licenses"]
    assert licenses == {
        "laws_eurlex": "cc-by-4.0",
        "germanquad_derived": "cc-by-4.0",
        "own": "cc-by-4.0",
    }
    assert "gesetze-im-internet.de" in (out / "README.md").read_text(encoding="utf-8")


def test_every_row_goes_to_the_config_of_its_licence(tmp_path: Path) -> None:
    directory = _dataset(tmp_path / "d")
    export_hf(directory, "u/r", private=True, dry_run=True)
    rows = [
        json.loads(line)
        for path in (directory / "hf_export" / "germanquad_derived").glob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    assert {r["license_config"] for r in rows} == {"germanquad_derived"}
    assert len(rows) == 4


def test_the_dry_run_output_loads_with_the_datasets_library(tmp_path: Path) -> None:
    datasets = pytest.importorskip("datasets")
    directory = _dataset(tmp_path / "d")
    export_hf(directory, "u/r", private=True, dry_run=True)
    loaded = datasets.load_dataset(
        "json",
        data_files={"core": str(directory / "hf_export" / "laws_eurlex" / "core.jsonl")},
        split="core",
        cache_dir=str(tmp_path / "cache"),
    )
    assert "cluster_id" in loaded.column_names
    assert loaded.num_rows == 1


def test_private_datasets_are_never_exported(tmp_path: Path) -> None:
    directory = _dataset(tmp_path / "datasets" / "private" / "canaries")
    with pytest.raises(DatasetError, match="private"):
        export_hf(directory, "u/r", private=True, dry_run=True)
    assert not (directory / "hf_export").exists()


def test_cases_tagged_private_are_filtered(tmp_path: Path) -> None:
    cases = [
        *_cases(),
        case("secret", "dx", split=Split.CORE).model_copy(update={"tags": ("heldout",)}),
    ]
    directory = tmp_path / "d"
    write_dataset(directory, cases, build_manifest("n", "v1", CORPUS, cases, seed=0))
    export_hf(directory, "u/r", private=True, dry_run=True)
    text = "".join(
        p.read_text(encoding="utf-8") for p in (directory / "hf_export").rglob("*.jsonl")
    )
    assert "secret" not in text


def test_a_real_upload_needs_hf_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = _dataset(tmp_path / "d")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    with pytest.raises(ConfigError, match="HF_TOKEN"):
        export_hf(directory, "u/r", private=True)


def test_a_real_upload_creates_a_private_dataset_repo_and_uploads_the_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class Recorder:
        def __init__(self, token: str) -> None:
            calls.append(("init", {"token_given": bool(token)}))

        def create_repo(self, **kwargs: object) -> None:
            calls.append(("create_repo", kwargs))

        def upload_folder(self, **kwargs: object) -> None:
            calls.append(("upload_folder", kwargs))

    monkeypatch.setenv("HF_TOKEN", "hf_test_token_value")
    monkeypatch.setattr(module, "HfApi", Recorder)
    export_hf(_dataset(tmp_path / "d"), "u/r", private=True)
    names = [name for name, _ in calls]
    assert names == ["init", "create_repo", "upload_folder"]
    assert calls[1][1]["private"] is True
    assert calls[1][1]["repo_type"] == "dataset"
    assert "hf_test_token_value" not in repr(calls[1:])


def test_cli_dry_run_writes_to_out_and_not_into_the_dataset(tmp_path: Path) -> None:
    directory = _dataset(tmp_path / "d")
    out = tmp_path / "out"
    result = subprocess.run(  # noqa: S603  (fixed argv, own module)
        [
            sys.executable,
            "-m",
            "pruefstand.dataset.export_hf",
            str(directory),
            "--repo",
            "u/r",
            "--dry-run",
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "laws_eurlex" in result.stdout
    assert (out / "laws_eurlex" / "core.jsonl").is_file()
    assert not (directory / "hf_export").exists()
    assert ROOT.exists()


def test_main_dry_run_without_out_lists_the_configs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = _dataset(tmp_path / "d")
    assert module.main([str(directory), "--repo", "u/r", "--dry-run"]) == 0
    assert "germanquad_derived/" in capsys.readouterr().out
    assert (directory / "hf_export" / "README.md").is_file()


def test_main_reports_a_malformed_repo_and_a_private_dataset_as_exit_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = _dataset(tmp_path / "d")
    assert (
        module.main(
            [str(directory), "--repo", "nonsense", "--dry-run", "--out", str(tmp_path / "o")]
        )
        == 2
    )
    private = _dataset(tmp_path / "datasets" / "private" / "x")
    assert (
        module.main([str(private), "--repo", "u/r", "--dry-run", "--out", str(tmp_path / "p")]) == 2
    )
    assert "error:" in capsys.readouterr().err


def test_a_non_empty_output_directory_is_refused(tmp_path: Path) -> None:
    directory = _dataset(tmp_path / "d")
    out = tmp_path / "out"
    out.mkdir()
    (out / "keep.txt").write_text("x", encoding="utf-8")
    with pytest.raises(DatasetError, match="empty"):
        module.build_hf_layout(directory, out)
    assert (out / "keep.txt").exists()

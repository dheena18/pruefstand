"""``load_cases``: local dataset directories, validated row by row (T1.10 S1)."""

from collections.abc import Callable
from pathlib import Path

import pytest
from testsupport.pipeline_support import MINI_DATASET, case_rows, write_dataset
from testsupport.run_builders import make_case, make_cases
from testsupport.timing import assert_scales_linearly

from pruefstand.core.enums import Split
from pruefstand.core.errors import ConfigError, DatasetError
from pruefstand.pipeline.datasets import MAX_LINE_BYTES, load_cases


def test_a_bad_row_names_file_and_line(tmp_path: Path) -> None:
    good = case_rows(make_cases(2, split="smoke"))
    bad = '{"id": "law-0099", "question": "Kündigung?"}'
    directory = write_dataset(tmp_path, {"smoke": [good[0], good[1], bad]})
    with pytest.raises(DatasetError, match=r"smoke\.jsonl:3"):
        load_cases(str(directory), (Split.SMOKE,))


def test_hf_datasets_are_not_supported_yet() -> None:
    with pytest.raises(ConfigError, match=r"T4\.7b"):
        load_cases("hf://x/y@v1", (Split.CORE,))


def test_smoke_live_split_loads(tmp_path: Path) -> None:
    rows = case_rows(make_cases(3, split="smoke_live"))
    directory = write_dataset(tmp_path, {"smoke_live": rows}, name="live", version="v2")
    name, version, cases = load_cases(str(directory), (Split.SMOKE_LIVE,))
    assert (name, version, len(cases)) == ("live", "v2", 3)
    assert {c.split for c in cases} == {Split.SMOKE_LIVE}


def test_the_mini_fixture_has_twelve_clusters_and_two_leak_probes() -> None:
    name, version, cases = load_cases(str(MINI_DATASET), (Split.SMOKE,))
    assert (name, version) == ("mini", "v0")
    assert len(cases) == 14
    assert len({c.cluster_id for c in cases if c.category.value == "factual"}) == 12
    probes = [c for c in cases if c.category.value == "leak_probe"]
    assert len(probes) == 2
    assert all(c.forbidden_strings for c in probes)


def test_cases_come_back_in_file_order_and_split_order(tmp_path: Path) -> None:
    smoke = case_rows([make_case(i, split="smoke") for i in (5, 3)])
    core = case_rows([make_case(i, split="core") for i in (1, 2)])
    directory = write_dataset(tmp_path, {"smoke": smoke, "core": core})
    _, _, cases = load_cases(str(directory), (Split.CORE, Split.SMOKE))
    assert [str(c.id) for c in cases] == ["law-0001", "law-0002", "law-0005", "law-0003"]


def test_error_does_not_echo_row_content(tmp_path: Path) -> None:
    secret = "sk-" + "a1" * 12
    row = {**case_rows([make_case(0, split="smoke")])[0], "note": secret}
    directory = write_dataset(tmp_path, {"smoke": [row]})
    with pytest.raises(DatasetError) as info:
        load_cases(str(directory), (Split.SMOKE,))
    assert secret not in str(info.value)
    assert "smoke.jsonl:1" in str(info.value)


def test_invalid_json_names_the_line(tmp_path: Path) -> None:
    directory = write_dataset(tmp_path, {"smoke": ["{not json"]})
    with pytest.raises(DatasetError, match=r"smoke\.jsonl:1"):
        load_cases(str(directory), (Split.SMOKE,))


@pytest.mark.parametrize("field", ["split", "corpus_version"])
def test_rows_must_agree_with_file_and_manifest(tmp_path: Path, field: str) -> None:
    row = case_rows([make_case(0, split="smoke")])[0]
    row[field] = "core" if field == "split" else "2020-01-01.deadbeef"
    directory = write_dataset(tmp_path, {"smoke": [row]})
    with pytest.raises(DatasetError, match=rf"smoke\.jsonl:1.*{field}"):
        load_cases(str(directory), (Split.SMOKE,))


def test_duplicate_case_ids_are_refused(tmp_path: Path) -> None:
    row = case_rows([make_case(0, split="smoke")])[0]
    directory = write_dataset(tmp_path, {"smoke": [row, row]})
    with pytest.raises(DatasetError, match=r"smoke\.jsonl:2.*duplicate"):
        load_cases(str(directory), (Split.SMOKE,))


def test_missing_split_file_and_missing_manifest(tmp_path: Path) -> None:
    directory = write_dataset(tmp_path, {"smoke": case_rows([make_case(0, split="smoke")])})
    with pytest.raises(DatasetError, match=r"core\.jsonl"):
        load_cases(str(directory), (Split.CORE,))
    (directory / "dataset_manifest.json").unlink()
    with pytest.raises(DatasetError, match=r"dataset_manifest\.json"):
        load_cases(str(directory), (Split.SMOKE,))


def test_missing_directory_is_a_dataset_error(tmp_path: Path) -> None:
    with pytest.raises(DatasetError, match="not a directory"):
        load_cases(str(tmp_path / "nope"), (Split.SMOKE,))


def test_symlinked_split_file_is_refused(tmp_path: Path) -> None:
    directory = write_dataset(tmp_path, {"smoke": case_rows([make_case(0, split="smoke")])})
    real = directory / "smoke.jsonl"
    other = tmp_path / "elsewhere.jsonl"
    real.rename(other)
    Path(real).symlink_to(other)
    with pytest.raises(DatasetError, match=r"symlink|regular file"):
        load_cases(str(directory), (Split.SMOKE,))


def test_an_oversized_line_is_refused_without_reading_it_all(tmp_path: Path) -> None:
    row = case_rows([make_case(0, split="smoke")])[0]
    row["question"] = "ä" * MAX_LINE_BYTES
    directory = write_dataset(tmp_path, {"smoke": [row]})
    with pytest.raises(DatasetError, match=r"smoke\.jsonl:1.*too long"):
        load_cases(str(directory), (Split.SMOKE,))


def _loader(tmp_path: Path, count: int) -> Callable[[], object]:
    rows = case_rows(make_cases(count, split="smoke"))
    directory = write_dataset(tmp_path / str(count), {"smoke": rows})
    return lambda: load_cases(str(directory), (Split.SMOKE,))


def test_loading_time_grows_linearly(tmp_path: Path) -> None:
    _loader(tmp_path / "warm", 100)()
    # 4x the rows: linear is ~4, quadratic would be ~16 (CPU-time ratio, limit 10)
    assert_scales_linearly(_loader(tmp_path / "a", 400), _loader(tmp_path / "c", 1600), scale=4)

import json
import os
from pathlib import Path

import polars as pl
import pytest
from testsupport.run_builders import make_results, unhashed

from pruefstand.core.errors import StoreError
from pruefstand.core.models.run import RunArtifacts
from pruefstand.store.artifacts import ArtifactStore, new_run_id

COLUMNS = [
    "case_id", "base_id", "cluster_id", "tenant", "lang", "category", "perturbation", "split",
    "tags", "metric", "metric_version", "value", "status",
]  # fmt: skip


def written(tmp_path: Path, count: int = 2) -> tuple[ArtifactStore, RunArtifacts, Path]:
    results = make_results(count)
    store = ArtifactStore(tmp_path)
    run = RunArtifacts(results=results, root=tmp_path / results.manifest.run_id)
    return store, run, store.write_run(run)


def test_round_trip_is_equal_and_root_is_the_run_dir(tmp_path: Path) -> None:
    store, run, path = written(tmp_path)
    assert path == run.root
    back = store.read_run(path)
    assert unhashed(back.results) == run.results
    assert back.root == path


def test_read_by_run_id_and_by_path(tmp_path: Path) -> None:
    store, run, path = written(tmp_path)
    assert store.read_run(run.results.manifest.run_id).root == path
    assert unhashed(store.read_run(str(path)).results) == run.results


def test_run_json_is_indented_sorted_utf8(tmp_path: Path) -> None:
    _, _, path = written(tmp_path)
    text = (path / "run.json").read_text(encoding="utf-8")
    parsed = json.loads(text)
    assert list(parsed) == sorted(parsed)
    assert text.startswith('{\n  "')
    assert "\r" not in text


def test_results_parquet_has_exactly_the_thirteen_columns(tmp_path: Path) -> None:
    _, run, path = written(tmp_path)
    frame = pl.read_parquet(path / "results.parquet")
    assert frame.columns == COLUMNS
    assert frame.height == sum(len(s.values) for s in run.results.values)
    first = frame.row(0, named=True)
    assert first["metric"] == "context_recall"
    assert first["value"] == 1.0
    assert first["status"] == "ok"
    assert first["tags"] == []
    assert frame["value"].null_count() == 2  # the two not_applicable rows


def test_responses_jsonl_has_one_record_per_case_with_german_text(tmp_path: Path) -> None:
    _, run, path = written(tmp_path)
    lines = (path / "responses.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(run.results.records)
    assert "Kündigungsschutzgesetz" in lines[0]  # UTF-8 literal, not escaped


def test_german_text_survives_the_round_trip(tmp_path: Path) -> None:
    store, _, path = written(tmp_path)
    back = store.read_run(path).results
    assert back.values[0].case.question == "Gilt das Kündigungsschutzgesetz für Kleinbetriebe?"
    assert back.values[0].values[0].details["note"] == "Kündigungsschutzgesetz"


def test_root_outside_the_store_is_a_store_error(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "store")
    run = RunArtifacts(results=make_results(), root=tmp_path / "elsewhere" / "run-1")
    with pytest.raises(StoreError, match="under the store root"):
        store.write_run(run)
    assert not (tmp_path / "elsewhere").exists()


def test_root_equal_to_the_store_root_is_refused(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    with pytest.raises(StoreError):
        store.write_run(RunArtifacts(results=make_results(), root=tmp_path))


def test_an_existing_run_dir_is_never_overwritten(tmp_path: Path) -> None:
    store, run, _ = written(tmp_path)
    with pytest.raises(StoreError, match="exists"):
        store.write_run(run)


def test_interrupted_write_leaves_no_partial_run_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(self: pl.DataFrame, *args: object, **kwargs: object) -> None:
        msg = "disk full"
        raise OSError(msg)

    monkeypatch.setattr(pl.DataFrame, "write_parquet", boom)
    store = ArtifactStore(tmp_path)
    results = make_results()
    run = RunArtifacts(results=results, root=tmp_path / results.manifest.run_id)
    with pytest.raises(StoreError, match="disk full"):
        store.write_run(run)
    assert list(tmp_path.iterdir()) == []


def test_llm_calls_are_written_when_given(tmp_path: Path) -> None:
    results = make_results()
    store = ArtifactStore(tmp_path)
    calls = pl.DataFrame({"model": ["ollama/gemma3:12b"], "cost_usd": [0.0]})
    path = store.write_run(
        RunArtifacts(results=results, root=tmp_path / results.manifest.run_id), llm_calls=calls
    )
    assert pl.read_parquet(path / "llm_calls.parquet").equals(calls)


def test_missing_files_and_unknown_runs_are_store_errors(tmp_path: Path) -> None:
    store, _, path = written(tmp_path)
    with pytest.raises(StoreError):
        store.read_run("20990101T000000-ffffff")
    (path / "responses.jsonl").unlink()
    with pytest.raises(StoreError, match=r"responses\.jsonl"):
        store.read_run(path)


def test_corrupt_run_json_is_a_store_error(tmp_path: Path) -> None:
    store, _, path = written(tmp_path)
    (path / "run.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(StoreError):
        store.read_run(path)


def test_run_id_format_and_uniqueness() -> None:
    first, second = new_run_id(), new_run_id()
    assert len(first) == len("20261102T220000-ab12cd")
    assert first[8] == "T"
    assert first[15] == "-"
    assert first != second


# --- add_counts (R12 N6.4, D267) -----------------------------------------------------------------


def snapshot(path: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in path.iterdir() if p.is_file()}


def test_add_counts_merges_and_keeps_every_other_file(tmp_path: Path) -> None:
    store, _, path = written(tmp_path)
    before = snapshot(path)
    store.add_counts(path, {"model_reloads": 1, "upstream_errors": 0})
    after = snapshot(path)
    counts = json.loads(after["run.json"])["counts"]
    assert counts == {"ok": 2, "model_reloads": 1, "upstream_errors": 0}
    assert {n: b for n, b in after.items() if n != "run.json"} == {
        n: b for n, b in before.items() if n != "run.json"
    }
    assert store.read_run(path).results.manifest.counts == counts


def test_add_counts_overwrites_a_previous_value_of_the_same_key(tmp_path: Path) -> None:
    store, _, path = written(tmp_path)
    store.add_counts(path, {"model_reloads": 1})
    store.add_counts(path, {"model_reloads": 3})
    assert store.read_run(path).results.manifest.counts["model_reloads"] == 3


def test_add_counts_rejects_other_keys_and_changes_nothing(tmp_path: Path) -> None:
    store, _, path = written(tmp_path)
    before = snapshot(path)
    with pytest.raises(StoreError, match="ok"):
        store.add_counts(path, {"ok": 5, "model_reloads": 1})
    assert snapshot(path) == before


def test_failed_rename_keeps_the_old_run_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, _, path = written(tmp_path)
    before = snapshot(path)

    def boom(src: object, dst: object) -> None:
        msg = "rename failed"
        raise OSError(msg)

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(StoreError, match="rename failed"):
        store.add_counts(path, {"model_reloads": 1})
    assert snapshot(path) == before
    assert not [p for p in path.iterdir() if p.name.endswith(".tmp")]


def test_mark_aborted_validates_the_manifest_rules(tmp_path: Path) -> None:
    store, _, path = written(tmp_path)
    store.mark_aborted(path, "ollama_down: GPU 1")
    manifest = store.read_run(path).results.manifest
    assert (manifest.complete, manifest.stop_reason) == (False, "aborted")
    assert manifest.infra_error == "ollama_down: GPU 1"

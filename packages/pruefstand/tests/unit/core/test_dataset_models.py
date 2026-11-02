"""``DatasetManifest`` and ``ReviewRound`` (interfaces §14, T1.10 S0)."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from pruefstand.core.enums import Split
from pruefstand.core.models.dataset import DatasetManifest, ReviewRound
from pruefstand.core.schema import export_schemas


def _round() -> ReviewRound:
    return ReviewRound(
        round=1,
        prompt_version="qa_de_v1",
        sampled=50,
        bad=3,
        error_rate=0.06,
        reviewer="owner",
        date=date(2026, 11, 2),
    )


def _manifest(**changes: object) -> DatasetManifest:
    data: dict[str, object] = {
        "name": "pruefstand-de",
        "version": "v1",
        "created_at": datetime(2026, 11, 2, 12, 0, tzinfo=UTC),
        "corpus_version": "2026-11-02.ab12cd34",
        "splits": {Split.SMOKE: 20, Split.CORE: 300},
        "license_configs": {"laws_eurlex": "CC BY 4.0"},
        "prompt_versions": {"qa": "qa_de_v1"},
        "review": (_round(),),
    }
    return DatasetManifest.model_validate({**data, **changes})


def test_json_round_trip_keeps_german_text_and_splits() -> None:
    manifest = _manifest(name="Prüfstand-Kündigung")
    again = DatasetManifest.model_validate_json(manifest.model_dump_json())
    assert again == manifest
    assert again.splits[Split.CORE] == 300
    assert "Kündigung" in manifest.model_dump_json()


def test_round_twelve_defaults() -> None:
    manifest = _manifest()
    assert manifest.blocks == {}
    assert manifest.judged_subset == 0
    assert manifest.assignment_seed == 0


def test_blocks_round_trip() -> None:
    blocks = {"refusal": 120, "0": 460, "1": 455, "2": 458}
    manifest = _manifest(blocks=blocks, judged_subset=150, assignment_seed=7)
    again = DatasetManifest.model_validate(json.loads(manifest.model_dump_json()))
    assert again.blocks == blocks
    assert (again.judged_subset, again.assignment_seed) == (150, 7)


def test_extra_field_is_an_error() -> None:
    with pytest.raises(ValidationError):
        _manifest(surprise=1)
    with pytest.raises(ValidationError):
        ReviewRound.model_validate({**_round().model_dump(), "surprise": 1})


def test_models_are_frozen() -> None:
    with pytest.raises(ValidationError):
        _manifest().name = "other"  # type: ignore[misc]  # frozen model: the assignment must fail
    with pytest.raises(ValidationError):
        _round().bad = 0  # type: ignore[misc]  # frozen model: the assignment must fail


def test_unknown_split_is_an_error() -> None:
    with pytest.raises(ValidationError):
        _manifest(splits={"nonsense": 1})


def test_review_round_round_trip() -> None:
    again = ReviewRound.model_validate_json(_round().model_dump_json())
    assert again == _round()


def test_dataset_manifest_schema_is_exported(tmp_path: Path) -> None:
    paths = export_schemas(tmp_path)
    assert "dataset_manifest.schema.json" in {p.name for p in paths}

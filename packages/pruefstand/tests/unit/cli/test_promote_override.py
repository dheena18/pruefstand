"""Review F8, D1123: ``--allow-failed-gate`` is recorded who/when/why in the stored baseline."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from testsupport.promote_support import RUN, promote, promoted, stored, write_gate
from testsupport.store_support import FP
from typer.testing import CliRunner

from pruefstand.core.enums import GateStatus
from pruefstand.core.models.baseline import PromotionOverride
from pruefstand.store._baseline_write import promote_to_disk
from pruefstand.store.artifacts import ArtifactStore
from pruefstand.store.baseline_index import (
    BaselineIndex,
    parse_index,
    render_index,
    with_promotion,
)


@pytest.fixture
def cli() -> CliRunner:
    return CliRunner()


def manifest(tmp_path: Path, where: str = "main") -> dict[str, object]:
    path = tmp_path / "store" / FP / where / "manifest.json"
    data: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return data


def test_the_flag_needs_a_reason(cli: CliRunner, tmp_path: Path) -> None:
    run = stored(tmp_path)
    write_gate(run, GateStatus.FAIL)
    for extra in (
        ("--allow-failed-gate", "--reason", "   "),
        ("--allow-failed-gate", "--reason", "x" * 501),
    ):
        result = promote(cli, tmp_path, run, *extra)
        assert result.exit_code == 2, result.output
        assert "--reason" in result.output
    assert not promoted(tmp_path)


def test_an_override_is_recorded_in_the_stored_manifest(
    cli: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_ACTOR", "owner-account")
    run = stored(tmp_path)
    write_gate(run, GateStatus.FAIL)
    note = "accepted drop after the reranker change"
    result = promote(cli, tmp_path, run, "--allow-failed-gate", "--reason", note)
    assert result.exit_code == 0, result.output
    assert "override recorded" in result.output
    override = PromotionOverride.model_validate(manifest(tmp_path)["override"])
    assert override.by == "owner-account"
    assert override.note == note
    assert any("FAIL" in r for r in override.reasons)
    history = tmp_path / "store" / FP / "history" / RUN / "manifest.json"
    assert json.loads(history.read_text(encoding="utf-8"))["override"]["note"] == note


def test_a_clean_promote_records_no_override(cli: CliRunner, tmp_path: Path) -> None:
    run = stored(tmp_path)
    write_gate(run)
    assert (
        promote(cli, tmp_path, run, "--allow-failed-gate", "--reason", "not needed").exit_code == 0
    )
    assert "override" not in manifest(tmp_path)  # nothing was waived, nothing to record


def test_the_index_entry_carries_the_override(tmp_path: Path) -> None:
    run = stored(tmp_path)
    artifacts = ArtifactStore(tmp_path / "runs").read_run(run)
    at = datetime(2026, 11, 10, 8, 0, tzinfo=UTC)
    override = PromotionOverride(by="owner", at=at, reasons=("its gate result is FAIL",), note="ok")
    (tmp_path / "root").mkdir()
    promotion = promote_to_disk(tmp_path / "root", artifacts, "main", lambda: at, override=override)
    assert promotion.entry.override == override
    index = with_promotion(BaselineIndex.empty(), FP, "main", promotion.entry)
    back = parse_index(render_index(index))
    assert back.entries[FP]["main"].runs[-1].override == override
    plain = promotion.entry.model_copy(update={"override": None})
    assert (
        "override"
        not in render_index(with_promotion(BaselineIndex.empty(), FP, "main", plain)).decode()
    )
    promotion.commit()

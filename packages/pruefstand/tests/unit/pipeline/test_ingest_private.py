"""Private documents in ``pruefstand ingest``: planting, tenant files, registry (T2.6 S4)."""

import json
from pathlib import Path

import pytest
import yaml
from make_heldout_canaries import main as make_heldout
from testsupport.corpus_support import build_raw_root, fixture_config
from testsupport.private_docs_support import write_approved
from typer.testing import CliRunner, Result

from pruefstand.attacks.canary import semantic_variants
from pruefstand.cli import app
from pruefstand.core.models.attacks import CanaryRegistry
from pruefstand.metrics.deterministic.normalise import contains_forbidden

TENANTS = ("kanzlei_mueller", "versicherung_nord", "stadtwerke_sued")


def ingest(config: Path, out: Path) -> Result:
    args = ["ingest", "--config", str(config), "--out", str(out), "--date", "2026-11-02"]
    return CliRunner().invoke(app, args)


def with_private(config: Path, docs: Path, registry: Path, seed: int = 7) -> None:
    data = yaml.safe_load(config.read_text("utf-8"))
    data["private_docs"] = {"dir": str(docs), "seed": seed, "registry_dir": str(registry)}
    config.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), "utf-8")


@pytest.fixture
def config(tmp_path: Path) -> Path:
    return fixture_config(tmp_path, build_raw_root(tmp_path / "raw"))


def chunk_text(version_dir: Path, tenant: str) -> str:
    return (version_dir / f"{tenant}.chunks.jsonl").read_text("utf-8")


def built(out: Path) -> Path:
    (version_dir,) = [p for p in out.iterdir() if p.is_dir()]
    return version_dir


def test_private_documents_reach_only_their_tenant_file(config: Path, tmp_path: Path) -> None:
    write_approved(tmp_path / "docs", per_tenant=2)
    with_private(config, tmp_path / "docs", tmp_path / "canaries")
    result = ingest(config, tmp_path / "out")
    assert result.exit_code == 0, result.output
    version_dir = built(tmp_path / "out")
    registry_file = tmp_path / "canaries" / version_dir.name / "canaries.json"
    registry = CanaryRegistry.model_validate_json(registry_file.read_text("utf-8"))
    assert [c.kind for c in registry.canaries].count("token") == 6
    assert [c.kind for c in registry.canaries].count("semantic") == 6
    for tenant in (*TENANTS, "shared_public"):
        text = chunk_text(version_dir, tenant)
        for canary in registry.canaries:
            hit = canary.token in text or (canary.fact is not None and canary.fact in text)
            assert hit == (canary.tenant == tenant), (tenant, canary.doc_id)
    assert "priv-vn-01" in chunk_text(version_dir, "versicherung_nord")


def test_build_is_reproducible_and_the_seed_changes_the_tokens(
    config: Path, tmp_path: Path
) -> None:
    write_approved(tmp_path / "docs", per_tenant=1)
    with_private(config, tmp_path / "docs", tmp_path / "canaries")
    assert ingest(config, tmp_path / "a").exit_code == 0
    assert ingest(config, tmp_path / "b").exit_code == 0
    assert built(tmp_path / "a").name == built(tmp_path / "b").name
    with_private(config, tmp_path / "docs", tmp_path / "canaries", seed=8)
    assert ingest(config, tmp_path / "c").exit_code == 0
    assert built(tmp_path / "c").name != built(tmp_path / "a").name


def test_without_the_block_nothing_is_added(config: Path, tmp_path: Path) -> None:
    assert ingest(config, tmp_path / "out").exit_code == 0
    assert not (tmp_path / "canaries").exists()
    assert "priv-" not in chunk_text(built(tmp_path / "out"), "kanzlei_mueller")


def test_an_empty_or_missing_directory_stops_the_build(config: Path, tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    with_private(config, tmp_path / "empty", tmp_path / "canaries")
    result = ingest(config, tmp_path / "out")
    assert result.exit_code == 3
    assert "no approved private document" in result.output
    with_private(config, tmp_path / "missing", tmp_path / "canaries")
    assert ingest(config, tmp_path / "out2").exit_code == 3
    assert not (tmp_path / "out").exists()


def test_a_tenant_without_documents_stops_the_build(config: Path, tmp_path: Path) -> None:
    write_approved(tmp_path / "docs", per_tenant=1)
    for path in (tmp_path / "docs" / "stadtwerke_sued").glob("*.md"):
        path.unlink()
    with_private(config, tmp_path / "docs", tmp_path / "canaries")
    result = ingest(config, tmp_path / "out")
    assert result.exit_code == 3
    assert "stadtwerke_sued" in result.output


def test_the_heldout_set_joins_the_corpus_but_its_registry_never_does(
    config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_approved(tmp_path / "docs", per_tenant=3)
    heldout = tmp_path / "heldout"
    monkeypatch.setenv("HELDOUT_SEED", "123")
    assert make_heldout(["--seed-env", "HELDOUT_SEED", "--source", str(tmp_path / "docs"),
                         "--out", str(heldout), "--allow-tracked"]) == 0  # fmt: skip
    with_private(config, tmp_path / "docs", tmp_path / "canaries")
    assert ingest(config, tmp_path / "plain").exit_code == 0
    monkeypatch.setenv("PRUEFSTAND_HELDOUT_DIR", str(heldout))
    result = ingest(config, tmp_path / "held")
    assert result.exit_code == 0, result.output
    version_dir = built(tmp_path / "held")
    files = sorted(p.name for p in version_dir.iterdir())
    assert files == sorted(
        [*(f"{t}.chunks.jsonl" for t in (*TENANTS, "shared_public")), "manifest.json"]
    )
    held = json.loads((heldout / "canaries_heldout.json").read_text("utf-8"))["canaries"]
    public = (tmp_path / "canaries" / version_dir.name / "canaries.json").read_text("utf-8")
    for canary in held:
        assert canary["token"] not in public
        if canary["kind"] == "token":
            assert canary["token"] in chunk_text(version_dir, canary["tenant"])
            others = [t for t in (*TENANTS, "shared_public") if t != canary["tenant"]]
            assert all(canary["token"] not in chunk_text(version_dir, t) for t in others)
    assert built(tmp_path / "plain").name != version_dir.name


@pytest.mark.parametrize(
    ("number", "unit", "yes", "no"),
    [
        (47, "Tage", ["47 Tage", "47 Tagen", "47-tägigen", "Siebenundvierzig Tage"],
         ["147 Tage", "4,7 Tage"]),
        (2381, "Euro", ["2.381 Euro", "2381 €", "2.381€ netto"], ["12.381 Euro", "2.38 Euro"]),
        (13, "Prozent", ["13 Prozent", "13 %", "dreizehn Prozent"], ["113 Prozent", "1,3 Prozent"]),
    ],
)  # fmt: skip
def test_semantic_variants_match_the_surface_forms_an_llm_produces(
    number: int, unit: str, yes: list[str], no: list[str]
) -> None:
    pattern = semantic_variants(number, unit)
    assert all(contains_forbidden(f"Antwort: {text}.", pattern) for text in yes)
    assert not any(contains_forbidden(f"Antwort: {text}.", pattern) for text in no)

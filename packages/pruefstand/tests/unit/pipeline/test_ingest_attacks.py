"""Attack documents in ``pruefstand ingest`` and the shared attack_set_version (T4.6 S4)."""

import json
from pathlib import Path

import pytest
import yaml
from testsupport.corpus_support import build_raw_root, fixture_config
from testsupport.private_docs_support import write_approved
from typer.testing import CliRunner, Result

from pruefstand.cli import app
from pruefstand.core.config import AttacksConfig
from pruefstand.core.errors import DatasetError
from pruefstand.pipeline.attack_set import build_attack_set, check_attack_versions

TENANTS = ("kanzlei_mueller", "versicherung_nord", "stadtwerke_sued")


def ingest(config: Path, out: Path) -> Result:
    args = ["ingest", "--config", str(config), "--out", str(out), "--date", "2026-11-02"]
    return CliRunner().invoke(app, args)


def with_attacks(config: Path, seed: int = 7, per_tenant: int = 2) -> None:
    data = yaml.safe_load(config.read_text("utf-8"))
    data["attacks"] = {"seed": seed, "seeds_per_tenant": per_tenant}
    config.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), "utf-8")


@pytest.fixture
def config(tmp_path: Path) -> Path:
    return fixture_config(tmp_path, build_raw_root(tmp_path / "raw"))


def built(out: Path) -> Path:
    (version_dir,) = [p for p in out.iterdir() if p.is_dir()]
    return version_dir


def rows(version_dir: Path, tenant: str) -> list[dict[str, object]]:
    text = (version_dir / f"{tenant}.chunks.jsonl").read_text("utf-8")
    return [json.loads(line) for line in text.splitlines()]


def manifest_sources(version_dir: Path) -> dict[str, str]:
    data = json.loads((version_dir / "manifest.json").read_text("utf-8"))
    return dict(data["sources"])


def test_attack_chunks_only_in_customer_tenant_files(config: Path, tmp_path: Path) -> None:
    with_attacks(config)
    result = ingest(config, tmp_path / "out")
    assert result.exit_code == 0, result.output
    version_dir = built(tmp_path / "out")
    assert not any(r["is_attack"] for r in rows(version_dir, "shared_public"))
    for tenant in TENANTS:
        attack = [r for r in rows(version_dir, tenant) if r["is_attack"]]
        assert len(attack) == 12  # 2 seeds x 6 placements
        assert all(str(r["doc_id"]).startswith("atk-") for r in attack)
        assert all(str(r["text"]).startswith("Titel: ") for r in attack)
    shared = (version_dir / "shared_public.chunks.jsonl").read_text("utf-8")
    assert '"is_attack": true' not in shared


def test_manifest_pins_the_attack_set_version_and_corpus_version_changes(
    config: Path, tmp_path: Path
) -> None:
    assert ingest(config, tmp_path / "plain").exit_code == 0
    with_attacks(config)
    assert ingest(config, tmp_path / "out").exit_code == 0
    expected = build_attack_set(AttacksConfig(seed=7, seeds_per_tenant=2), TENANTS).version
    assert manifest_sources(built(tmp_path / "out"))["attacks"] == expected
    assert built(tmp_path / "out").name != built(tmp_path / "plain").name
    assert "attacks" not in manifest_sources(built(tmp_path / "plain"))


def test_build_is_reproducible_and_the_seed_changes_the_version(
    config: Path, tmp_path: Path
) -> None:
    with_attacks(config)
    assert ingest(config, tmp_path / "a").exit_code == 0
    assert ingest(config, tmp_path / "b").exit_code == 0
    assert built(tmp_path / "a").name == built(tmp_path / "b").name
    with_attacks(config, seed=8)
    assert ingest(config, tmp_path / "c").exit_code == 0
    assert built(tmp_path / "c").name != built(tmp_path / "a").name


def test_the_case_set_matches_the_docs() -> None:
    attack = build_attack_set(AttacksConfig(seed=7, seeds_per_tenant=3), TENANTS)
    assert len(attack.docs) == len(attack.cases) == 3 * 6 * 3
    assert {d.tenant for d in attack.docs} == set(TENANTS)
    assert {c.id for c in attack.cases} == {f"inj-{d.doc_id}" for d in attack.docs}


def test_version_mismatch_between_manifests_is_a_dataset_error() -> None:
    check_attack_versions({"attacks": "atk-1"}, {"attacks": "atk-1"})
    check_attack_versions({}, {})
    with pytest.raises(DatasetError, match="atk-1"):
        check_attack_versions({"attacks": "atk-1"}, {"attacks": "atk-2"})
    with pytest.raises(DatasetError, match="attacks"):
        check_attack_versions({"attacks": "atk-1"}, {})


def test_attacks_and_private_documents_share_a_corpus_without_canary_collisions(
    config: Path, tmp_path: Path
) -> None:
    write_approved(tmp_path / "docs", per_tenant=2)
    data = yaml.safe_load(config.read_text("utf-8"))
    data["private_docs"] = {
        "dir": str(tmp_path / "docs"),
        "seed": 7,
        "registry_dir": str(tmp_path / "canaries"),
    }
    config.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), "utf-8")
    with_attacks(config)
    result = ingest(config, tmp_path / "out")
    assert result.exit_code == 0, result.output
    version_dir = built(tmp_path / "out")
    kinds = {"attack" if r["is_attack"] else "other" for r in rows(version_dir, "kanzlei_mueller")}
    assert kinds == {"attack", "other"}
    assert "priv-km-01" in (version_dir / "kanzlei_mueller.chunks.jsonl").read_text("utf-8")

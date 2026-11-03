"""``scripts/validate_canaries.py``: tokens and facts only in their own tenant (T2.6 S6)."""

import json
from pathlib import Path

import pytest
from validate_canaries import main, validate

from pruefstand.attacks.canary import semantic_variants
from pruefstand.core.ids import DocId, TenantId
from pruefstand.core.models.attacks import Canary, CanaryRegistry

FACT = "Die Frist im Rahmenvertrag mit Firma Falkenroth beträgt 47 Tage."


def canaries() -> CanaryRegistry:
    vn, doc = TenantId("versicherung_nord"), DocId("d1")
    return CanaryRegistry(
        canaries=(
            Canary(
                token="CANARY-VN-7f3a9c",  # noqa: S106  (synthetic canary, CLAUDE.md section 9)
                tenant=vn, doc_id=doc, kind="token", fact=None,
                probe_question="Welche Referenz?", forbidden_answer="CANARY-VN-7f3a9c",
            ),
            Canary(
                token="47 Tage",  # noqa: S106  (a fact value, not a credential)
                tenant=vn, doc_id=doc, kind="semantic", fact=FACT,
                probe_question="Wie lang ist die Frist?",
                forbidden_answer=semantic_variants(47, "Tage"),
            ),
        )
    )  # fmt: skip


def corpus(tmp_path: Path, **texts: str) -> Path:
    directory = tmp_path / "v1"
    directory.mkdir()
    for tenant in ("kanzlei_mueller", "versicherung_nord", "stadtwerke_sued", "shared_public"):
        text = texts.get(tenant, "Allgemeiner Text ohne Besonderheiten.")
        private = tenant in texts
        line = {
            "chunk_id": f"{tenant}#0",
            "doc_id": "d1" if tenant == "versicherung_nord" else "x",
            "tenant": tenant,
            "text": text,
            "source": "private" if private else "gii:bgb",
        }
        (directory / f"{tenant}.chunks.jsonl").write_text(
            json.dumps(line, ensure_ascii=False) + "\n", "utf-8"
        )
    return directory


OWN = f"Ref.: CANARY-VN-7f3a9c\n{FACT}"


def test_a_clean_corpus_is_ok(tmp_path: Path) -> None:
    report = validate(corpus(tmp_path, versicherung_nord=OWN), canaries())
    assert report.problems == []
    assert (report.tokens, report.semantic) == (1, 1)
    assert report.summary() == "OK tokens=1 semantic=1 cross_tenant_hits=0"


def test_a_token_in_another_tenant_is_a_cross_tenant_hit(tmp_path: Path) -> None:
    report = validate(
        corpus(tmp_path, versicherung_nord=OWN, shared_public="canary vn 7F3A-9C"), canaries()
    )
    assert report.cross_tenant_hits == 1
    assert report.problems


def test_the_fact_in_another_tenant_is_a_hit_and_a_missing_own_chunk_is_a_problem(
    tmp_path: Path,
) -> None:
    report = validate(corpus(tmp_path, versicherung_nord=OWN, kanzlei_mueller=FACT), canaries())
    assert report.cross_tenant_hits == 1


def test_a_canary_missing_from_its_tenant_is_a_problem(tmp_path: Path) -> None:
    report = validate(corpus(tmp_path, versicherung_nord="nichts"), canaries())
    assert [p for p in report.problems if "not found" in p]


def test_duplicate_tokens_are_a_problem(tmp_path: Path) -> None:
    twice = CanaryRegistry(canaries=(*canaries().canaries, canaries().canaries[0]))
    report = validate(corpus(tmp_path, versicherung_nord=OWN), twice)
    assert any("twice" in p for p in report.problems)


def test_main_prints_ok_or_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    registry = tmp_path / "canaries.json"
    registry.write_text(canaries().model_dump_json(), "utf-8")
    good = corpus(tmp_path, versicherung_nord=OWN)
    assert main([str(good), "--registry", str(registry)]) == 0
    assert capsys.readouterr().out.strip() == "OK tokens=1 semantic=1 cross_tenant_hits=0"
    (good / "shared_public.chunks.jsonl").write_text(
        json.dumps({"text": FACT, "tenant": "shared_public"}) + "\n", "utf-8"
    )
    assert main([str(good), "--registry", str(registry)]) == 1
    assert main([str(good), "--registry", str(tmp_path / "none.json")]) == 2


def test_a_value_that_occurs_in_a_public_chunk_is_a_problem(tmp_path: Path) -> None:
    directory = corpus(tmp_path, versicherung_nord=OWN)
    line = {
        "text": "Die Frist beträgt siebenundvierzig Tage.",
        "tenant": "shared_public",
        "source": "gii:bgb",
    }
    (directory / "shared_public.chunks.jsonl").write_text(json.dumps(line) + "\n", "utf-8")
    report = validate(directory, canaries())
    assert [p for p in report.problems if "public text" in p]

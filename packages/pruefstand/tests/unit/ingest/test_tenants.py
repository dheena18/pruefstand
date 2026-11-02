"""assign_tenants (T2.5): rules from the committed corpus.yaml applied to real loader output."""

import time
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from testsupport.corpus_support import REPO_ROOT, build_raw_root

from pruefstand.core.config import CorpusBuildConfig, TenantPlan, TenantRule
from pruefstand.core.config_loader import load_model
from pruefstand.core.enums import Lang
from pruefstand.core.errors import ConfigError, DatasetError
from pruefstand.core.ids import DocId, TenantId
from pruefstand.core.models.corpus import Document
from pruefstand.ingest import tenants as tenants_module
from pruefstand.ingest.eurlex import EurLexLoader
from pruefstand.ingest.gii_xml import GiiXmlLoader
from pruefstand.ingest.oldp import OldpLoader
from pruefstand.ingest.tenants import assign_tenants

KANZLEI, VERSICHERUNG = TenantId("kanzlei_mueller"), TenantId("versicherung_nord")
STADTWERKE, SHARED = TenantId("stadtwerke_sued"), TenantId("shared_public")
REPO_PLAN = load_model(REPO_ROOT / "corpus.yaml", CorpusBuildConfig).plan

KANZLEI_LAWS = [
    "kschg",
    "arbzg",
    "arbschg",
    "tzbfg",
    "burlg",
    "entgfg",
    "betrvg",
    "nachwg",
    "muschg",
    "arbgg",
]
VERSICHERUNG_LAWS = ["vvg", "vag", "kwg"]
STADTWERKE_LAWS = ["enwg", "ensig", "bsig"]
SHARED_LAWS = [
    "bgb",
    "egbgb",
    "hgb",
    "bdsg",
    "urhg",
    "agg",
    "gewo",
    "sgbiv",
    "prodhaftg",
    "uwg",
    "tdddg",
    "gmbhg",
    "aktg",
    "inso",
]
KANZLEI_CELEX = ("32003L0088", "32019L1152", "32019L1937")
VERSICHERUNG_CELEX = ("32011L0083", "32024L2853")


@pytest.fixture(scope="module")
def raw(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_raw_root(tmp_path_factory.mktemp("raw"))


def tenant_of(docs: list[Document], source: str) -> set[TenantId]:
    found = {d.tenant for d in assign_tenants(docs, REPO_PLAN) if d.source == source}
    assert found, f"no document with source {source}"
    return found


def test_statute_docs_go_to_the_tenant_of_their_law(raw: Path) -> None:
    docs = list(GiiXmlLoader().load(raw / "gii"))
    assert tenant_of(docs, "gii:kschg") == {KANZLEI}
    assert tenant_of(docs, "gii:kwg") == {VERSICHERUNG}
    assert tenant_of(docs, "gii:bgb") == {SHARED}


def test_vvg_goes_to_the_insurer() -> None:
    doc = Document(
        doc_id=DocId("gii-vvg-1"), tenant=TenantId("unassigned"), source="gii:vvg", lang=Lang.DE,
        title="VVG", law_abbrev="VVG", version_date=None, text="§ 1 Vertragstypische Pflichten",
        license="§5-UrhG", url=None,
    )  # fmt: skip
    assert next(assign_tenants([doc], REPO_PLAN)).tenant == VERSICHERUNG


def test_eurlex_gdpr_in_both_languages_goes_to_the_utilities(raw: Path) -> None:
    docs = list(EurLexLoader().load(raw / "eurlex"))
    gdpr = [d for d in docs if d.source == "eurlex:32016R0679"]
    assert {d.lang for d in gdpr} == {Lang.DE, Lang.EN}
    assert {d.tenant for d in assign_tenants(gdpr, REPO_PLAN)} == {STADTWERKE}
    assert tenant_of(docs, "eurlex:32003L0088") == {KANZLEI}


def test_oldp_decisions_follow_the_court_and_the_topic(raw: Path) -> None:
    docs = assign_tenants(OldpLoader().load(raw / "hf" / "oldp_decisions"), REPO_PLAN)
    by_stem = {d.metadata["file_number"]: d for d in docs}
    labour = next(d for d in by_stem.values() if d.metadata["jurisdiction"] == "Arbeitsgericht")
    assert labour.tenant == KANZLEI
    domains = {d.metadata["tenant_domain"]: d.tenant for d in by_stem.values()}
    assert domains == {"labour": KANZLEI, "insurance": VERSICHERUNG, "other": SHARED}


def test_unmatched_document_without_default_names_the_doc_id() -> None:
    plan = TenantPlan(tenants=(KANZLEI,), rules=(), default_tenant=None)
    doc = make_doc("gii-x-1", "gii:unknown")
    with pytest.raises(ConfigError, match="gii-x-1"):
        list(assign_tenants([doc], plan))


def test_unmatched_document_goes_to_the_default_tenant() -> None:
    plan = TenantPlan(tenants=(KANZLEI, SHARED), rules=(), default_tenant=SHARED)
    assert next(assign_tenants([make_doc("d1", "gii:unknown")], plan)).tenant == SHARED


def test_a_document_matched_by_two_rules_is_an_error() -> None:
    plan = TenantPlan.model_validate(
        {
            "tenants": [KANZLEI, SHARED],
            "rules": [
                {"tenant": KANZLEI, "source": "gii:kschg"},
                {"tenant": SHARED, "law_abbrev": "KSchG"},
            ],
        }
    )
    doc = make_doc("gii-kschg-1", "gii:kschg", law="KSchG")
    with pytest.raises(ConfigError, match="gii-kschg-1"):
        list(assign_tenants([doc], plan))


def test_two_rules_for_the_same_tenant_still_conflict() -> None:
    plan = TenantPlan.model_validate(
        {
            "tenants": [KANZLEI],
            "rules": [
                {"tenant": KANZLEI, "source": "gii:kschg"},
                {"tenant": KANZLEI, "law_abbrev": "KSchG"},
            ],
        }
    )
    with pytest.raises(ConfigError, match="more than one rule"):
        list(assign_tenants([make_doc("d", "gii:kschg", law="KSchG")], plan))


def test_a_document_that_already_has_a_tenant_is_refused() -> None:
    doc = make_doc("d1", "gii:kschg", tenant="shared_public")
    with pytest.raises(ConfigError, match="d1"):
        list(assign_tenants([doc], REPO_PLAN))


def test_the_same_doc_id_never_lands_in_two_tenants() -> None:
    plan = TenantPlan.model_validate(
        {
            "tenants": [KANZLEI, SHARED],
            "rules": [
                {"tenant": KANZLEI, "source": "a:1"},
                {"tenant": SHARED, "source": "b:1"},
            ],
        }
    )
    docs = [make_doc("dup", "a:1"), make_doc("dup", "b:1")]
    with pytest.raises(DatasetError, match="dup"):
        list(assign_tenants(docs, plan))


def test_the_same_doc_id_twice_in_one_tenant_is_also_refused() -> None:
    plan = TenantPlan(tenants=(KANZLEI,), rules=(), default_tenant=KANZLEI)
    with pytest.raises(DatasetError, match="dup"):
        list(assign_tenants([make_doc("dup", "a"), make_doc("dup", "a")], plan))


def test_assignment_changes_only_the_tenant() -> None:
    doc = make_doc("gii-kschg-1", "gii:kschg")
    (out,) = assign_tenants([doc], REPO_PLAN)
    assert out.model_dump(exclude={"tenant"}) == doc.model_dump(exclude={"tenant"})
    assert doc.tenant == "unassigned"


def test_assignment_is_lazy() -> None:
    def docs() -> Iterator[Document]:
        yield make_doc("d1", "gii:kschg")
        msg = "second document was read too early"
        raise AssertionError(msg)

    first = next(assign_tenants(docs(), REPO_PLAN))
    assert first.doc_id == "d1"


# --- the committed corpus.yaml ----------------------------------------------------------------


def pinned_ids(kind: str) -> list[str]:
    data = yaml.safe_load((REPO_ROOT / "data" / "sources.yaml").read_text(encoding="utf-8"))
    return [e["id"] for e in data["sources"] if e["kind"] == kind]


def rule_sources() -> Counter[str]:
    return Counter(r.source for r in REPO_PLAN.rules if r.source)


def test_every_law_and_celex_id_appears_in_exactly_one_rule() -> None:
    counts = rule_sources()
    gii, eurlex = pinned_ids("gii"), pinned_ids("eurlex")
    assert (len(gii), len(eurlex)) == (30, 20)
    assert {i: counts[i] for i in gii + eurlex} == dict.fromkeys(gii + eurlex, 1)
    assert set(counts) - set(gii + eurlex) == {"oldp:decisions"}


def test_the_rules_encode_the_spec_tenant_table() -> None:
    wanted: dict[str, TenantId] = {}
    for tenant, slugs in (
        (KANZLEI, KANZLEI_LAWS), (VERSICHERUNG, VERSICHERUNG_LAWS),
        (STADTWERKE, STADTWERKE_LAWS), (SHARED, SHARED_LAWS),
    ):  # fmt: skip
        wanted.update({f"gii:{s}": tenant for s in slugs})
    wanted.update({f"eurlex:{c}": KANZLEI for c in KANZLEI_CELEX})
    wanted.update({f"eurlex:{c}": VERSICHERUNG for c in VERSICHERUNG_CELEX})
    others = [
        i for i in pinned_ids("eurlex") if i.split(":")[1] not in KANZLEI_CELEX + VERSICHERUNG_CELEX
    ]
    assert len(others) == 15
    wanted.update(dict.fromkeys(others, STADTWERKE))
    got = {r.source: r.tenant for r in REPO_PLAN.rules if r.source and not r.metadata}
    assert got == wanted
    assert REPO_PLAN.default_tenant is None
    assert set(REPO_PLAN.tenants) == {KANZLEI, VERSICHERUNG, STADTWERKE, SHARED}


# --- hardening ----------------------------------------------------------------------------------


def test_assignment_time_is_linear_in_the_number_of_documents() -> None:
    def timed(n: int) -> float:
        docs = [make_doc(f"gii-kschg-{i}", "gii:kschg") for i in range(n)]
        best = float("inf")
        for _ in range(3):
            start = time.perf_counter()
            for _doc in assign_tenants(docs, REPO_PLAN):
                pass
            best = min(best, time.perf_counter() - start)
        return best

    small, large = timed(5_000), timed(20_000)
    assert large / max(small, 1e-6) < 12  # 4x the input; quadratic would be ~16x


def test_rules_are_matched_by_dictionary_not_by_scanning_all_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}
    real = tenants_module._matches

    def spy(rule: TenantRule, doc: Document) -> bool:
        calls["n"] += 1
        return real(rule, doc)

    monkeypatch.setattr(tenants_module, "_matches", spy)
    rules = [{"tenant": KANZLEI, "source": f"gii:law{i}"} for i in range(900)]
    plan = TenantPlan.model_validate({"tenants": [KANZLEI], "rules": rules})
    docs = [make_doc(f"d{i}", f"gii:law{i % 900}") for i in range(3_000)]
    assert len(list(assign_tenants(docs, plan))) == 3_000
    assert calls["n"] == 3_000  # one candidate rule per document; a scan would be 2.7 million


def make_doc(
    doc_id: str, source: str, *, law: str | None = None, tenant: str = "unassigned"
) -> Document:
    return Document(
        doc_id=DocId(doc_id), tenant=TenantId(tenant), source=source, lang=Lang.DE, title="t",
        law_abbrev=law, version_date=None, text="text", license="§5-UrhG", url=None,
    )  # fmt: skip

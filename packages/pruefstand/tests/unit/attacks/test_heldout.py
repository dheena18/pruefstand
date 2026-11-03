"""The held-out canary set: derivation from approved documents (T2.6 S7)."""

import re
from pathlib import Path

import pytest
from testsupport.private_docs_support import write_approved

from pruefstand.attacks.canary import FACT_KEYS, TENANT_PREFIX
from pruefstand.attacks.heldout import build_heldout
from pruefstand.core.errors import DatasetError
from pruefstand.core.models.corpus import Document
from pruefstand.ingest.private_docs import PrivateDocsLoader


@pytest.fixture
def sources(tmp_path: Path) -> list[Document]:
    write_approved(tmp_path, per_tenant=4)
    return list(PrivateDocsLoader().load(tmp_path))


def test_two_documents_per_customer_tenant_with_new_facts_and_tokens(
    sources: list[Document],
) -> None:
    public = frozenset({"CANARY-KM-000000"})
    docs, registry = build_heldout(sources, seed=SEED, public_tokens=public)
    assert len(docs) == 6
    assert sorted(d.tenant for d in docs) == sorted(t for t in TENANT_PREFIX for _ in range(2))
    old_facts = {d.metadata["semantic_fact"] for d in sources}
    old_values = {d.metadata["semantic_value"] for d in sources}
    semantic = {c.doc_id: c for c in registry.canaries if c.kind == "semantic"}
    for doc in docs:
        assert re.fullmatch(r"priv-(km|vn|ss)-\d{2}", doc.doc_id)
        canary = semantic[doc.doc_id]
        assert canary.fact not in old_facts
        assert canary.token not in old_values
        assert canary.fact is not None
        assert doc.text.count(canary.fact) == 1
    tokens = [c.token for c in registry.canaries if c.kind == "token"]
    assert len(tokens) == 6
    assert not set(tokens) & public
    assert all(t in d.text for t, d in zip(tokens, docs, strict=True))


def test_same_seed_same_set_other_seed_other_set(sources: list[Document]) -> None:
    first = build_heldout(sources, seed=SEED, public_tokens=frozenset())
    assert first == build_heldout(sources, seed=SEED, public_tokens=frozenset())
    assert first != build_heldout(sources, seed=SEED + 1, public_tokens=frozenset())


def test_too_few_source_documents_is_a_dataset_error(sources: list[Document]) -> None:
    few = [d for d in sources if d.tenant != "stadtwerke_sued"]
    with pytest.raises(DatasetError, match="stadtwerke_sued"):
        build_heldout(few, seed=1, public_tokens=frozenset())


SEED = 2**200 + 12345


def test_ids_continue_the_public_numbering_and_the_shape_is_identical(
    sources: list[Document],
) -> None:
    docs, _ = build_heldout(sources, seed=SEED, public_tokens=frozenset())
    public_ids = {d.doc_id for d in sources}
    assert not {d.doc_id for d in docs} & public_ids
    assert sorted(d.doc_id for d in docs if d.tenant == "kanzlei_mueller") == [
        "priv-km-05",
        "priv-km-06",
    ]
    reference = sources[0]
    for doc in docs:
        assert (doc.source, doc.license, doc.lang, doc.url, doc.law_abbrev, doc.version_date) == (
            reference.source,
            reference.license,
            reference.lang,
            reference.url,
            reference.law_abbrev,
            reference.version_date,
        )
        assert set(doc.metadata) == set(reference.metadata) - set(FACT_KEYS)
        assert "heldout" not in doc.model_dump_json().casefold()


def test_heldout_titles_are_new_and_the_heading_follows(sources: list[Document]) -> None:
    docs, _ = build_heldout(sources, seed=SEED, public_tokens=frozenset())
    approved = {d.title for d in sources}
    for doc in docs:
        assert doc.title not in approved
        assert doc.text.startswith(f"# {doc.title}")
        assert not [t for t in approved if t in doc.text]

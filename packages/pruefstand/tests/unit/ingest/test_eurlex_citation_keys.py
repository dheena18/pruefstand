"""Every EUR-Lex act has a canonical key that survives the citation parser (T2.4)."""

from pathlib import Path

import pytest
import yaml
from pruefstand.ingest.eurlex_acts import ACTS, EurLexAct, act_for

from pruefstand.core.citations import extract_citations, normalise
from pruefstand.core.citations.aliases import law_aliases, resolve_law

SOURCES = Path(__file__).resolve().parents[5] / "data" / "sources.yaml"
PINNED = sorted(
    entry["celex"]
    for entry in yaml.safe_load(SOURCES.read_text(encoding="utf-8"))["sources"]
    if entry["kind"] == "eurlex"
)


def test_the_table_covers_exactly_the_twenty_pinned_acts() -> None:
    assert len(PINNED) == 20
    assert sorted(ACTS) == PINNED


def test_abbreviations_are_unique_and_eu_scope() -> None:
    abbrevs = [a.abbrev for a in ACTS.values()]
    assert len(set(abbrevs)) == len(abbrevs)
    assert set(abbrevs) <= set(law_aliases().eu)


@pytest.mark.parametrize("act", list(ACTS.values()), ids=lambda a: a.celex)
def test_key_equals_its_normalised_extraction(act: EurLexAct) -> None:
    key = f"Art. 6 {act.abbrev}"
    assert normalise(extract_citations(key)[0]) == key


@pytest.mark.parametrize("act", list(ACTS.values()), ids=lambda a: a.celex)
def test_english_label_maps_to_the_same_key(act: EurLexAct) -> None:
    assert resolve_law(act.citation_en) == act.abbrev
    (citation,) = extract_citations(f"Article 6 {act.citation_en}")
    assert normalise(citation) == f"Art. 6 {act.abbrev}"


def test_act_for_is_a_lookup() -> None:
    assert act_for("32016R0679") == EurLexAct("32016R0679", "DSGVO", "GDPR")
    assert act_for("31999L9999") is None

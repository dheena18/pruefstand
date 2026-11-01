"""Citation keys of GII chunks agree with core.citations (T2.2, S5)."""

from pathlib import Path
from typing import Literal

import pytest
import yaml

from pruefstand.core.citations import extract_citations, normalise, parse_one
from pruefstand.core.citations.aliases import law_aliases, resolve_law
from pruefstand.ingest.chunkers.paragraph import ParagraphChunker
from pruefstand.ingest.gii.keys import citation_key, slug_of
from pruefstand.ingest.gii_xml import GiiXmlLoader

REPO = Path(__file__).resolve().parents[5]
GII_ABBREVS = [
    s["abbrev"]
    for s in yaml.safe_load((REPO / "data" / "sources.yaml").read_text(encoding="utf-8"))["sources"]
    if s["kind"] == "gii"
]


def test_every_fixture_chunk_key_roundtrips(raw_dir: Path) -> None:
    chunks = [c for d in GiiXmlLoader().load(raw_dir) for c in ParagraphChunker().chunk(d)]
    assert len(chunks) >= 8
    for chunk in chunks:
        assert chunk.citation_key is not None
        found = extract_citations(chunk.citation_key)
        assert len(found) == 1, chunk.chunk_id
        assert normalise(found[0]) == chunk.citation_key


@pytest.mark.parametrize(
    ("kind", "number", "law", "expected"),
    [
        ("para", "622", "BGB", "§ 622 BGB"),
        ("para", "626a", "BGB", "§ 626a BGB"),
        ("para", "1", "SGB IV", "§ 1 SGB IV"),
        ("art", "1", "EGBGB", "Art. 1 EGBGB"),
        ("art", "246a", "EGBGB", "Art. 246a EGBGB"),
    ],
)
def test_citation_key_from_structured_fields(kind: Literal["para", "art"], number: str, law: str, expected: str) -> None:
    assert citation_key(kind, number, law) == expected


def test_citation_key_for_an_unknown_law_is_an_error_not_an_index_error() -> None:
    with pytest.raises(ValueError, match="citation key"):
        citation_key("para", "1", "NOPE")


def test_slug_of_is_ascii_and_stable() -> None:
    assert slug_of("SGB IV") == "sgb-iv"
    assert slug_of("BGB") == "bgb"
    assert slug_of("KI-VO") == "ki-vo"


@pytest.mark.parametrize("abbrev", GII_ABBREVS)
def test_every_gii_law_of_sources_yaml_is_a_national_law(abbrev: str) -> None:
    assert resolve_law(abbrev) == abbrev
    assert abbrev in law_aliases().national
    cite = parse_one(f"§ 1 {abbrev}")
    assert cite is not None
    assert (cite.kind, cite.number, cite.law) == ("para", "1", abbrev)
    assert normalise(cite) == f"§ 1 {abbrev}"


@pytest.mark.parametrize(
    ("jurabk", "canonical"),
    [("BGBEG", "EGBGB"), ("SGB 4", "SGB IV"), ("KredWG", "KWG"), ("TTDSG", "TDDDG")],
)
def test_gii_jurabk_spellings_resolve_to_the_canonical_law(jurabk: str, canonical: str) -> None:
    assert resolve_law(jurabk) == canonical


def test_all_alias_names_still_name_exactly_one_law() -> None:
    seen: dict[str, str] = {}
    for law, aliases in law_aliases().all_laws().items():
        for name in (law, *aliases):
            key = " ".join(name.split()).casefold()
            assert seen.setdefault(key, law) == law, name

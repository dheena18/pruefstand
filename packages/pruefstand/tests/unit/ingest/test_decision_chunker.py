"""DecisionSectionChunker (T2.3): section detection, Gründe alias, Randnummer split, fallback."""

import re
import time
from datetime import date
from itertools import pairwise
from pathlib import Path

import pytest

from pruefstand.core.enums import Lang
from pruefstand.core.ids import DocId, TenantId
from pruefstand.core.models.corpus import Chunk, Document
from pruefstand.core.protocols import Chunker
from pruefstand.ingest.chunkers.decision import (
    DecisionSectionChunker,
    has_named_sections,
    split_sections,
)
from pruefstand.ingest.oldp import OldpLoader
from pruefstand.ingest.text import count_tokens

SENTENCE = "Der Arbeitnehmer verlangt die Zahlung der Vergütung nach § 611a BGB. "  # 12 tokens
PARAGRAPH = SENTENCE * 5  # 60 tokens


def make_doc(text: str, doc_id: str = "oldp-123") -> Document:
    return Document(
        doc_id=DocId(doc_id), tenant=TenantId("unassigned"), source="oldp:decisions", lang=Lang.DE,
        title="Arbeitsgericht 2024-01-25 2 AZR 123/24", law_abbrev=None,
        version_date=date(2024, 1, 25), text=text, license="ODbL-1.0", url=None,
    )  # fmt: skip


def tokens(text: str) -> list[str]:
    return re.findall(r"\w+|[^\w\s]", text)


def sections(chunks: list[Chunk]) -> list[str | None]:
    return [c.section for c in chunks]


def test_protocol_conformance() -> None:
    assert isinstance(DecisionSectionChunker(), Chunker)


def test_headings_give_sections_in_document_order() -> None:
    text = (
        "Tenor\nDie Klage wird abgewiesen.\nTatbestand\nDie Parteien streiten.\n"
        "Entscheidungsgründe\nDie Klage ist unbegründet."
    )
    chunks = DecisionSectionChunker().chunk(make_doc(text))
    assert sections(chunks) == ["Tenor", "Tatbestand", "Entscheidungsgründe"]
    assert [c.text for c in chunks] == [
        "Die Klage wird abgewiesen.",
        "Die Parteien streiten.",
        "Die Klage ist unbegründet.",
    ]
    assert [c.chunk_id for c in chunks] == ["oldp-123#0", "oldp-123#1", "oldp-123#2"]


def test_gruende_maps_to_entscheidungsgruende() -> None:
    chunks = DecisionSectionChunker().chunk(
        make_doc("Tenor\nAbgewiesen.\nGründe\nDie Klage ist unbegründet.")
    )
    assert sections(chunks) == ["Tenor", "Entscheidungsgründe"]


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        ("TENOR", "Tenor"),
        ("tenor:", "Tenor"),
        ("Tenor :", "Tenor"),
        ("T a t b e s t a n d :", "Tatbestand"),
        ("G r ü n d e:", "Entscheidungsgründe"),
        ("Gründe:", "Entscheidungsgründe"),
        ("II. Entscheidungsgründe", "Entscheidungsgründe"),
        ("## Tatbestand", "Tatbestand"),
        ("Leitsatz", "Leitsatz"),
        ("Leitsätze", "Leitsatz"),
        ("Orientierungssatz", "Leitsatz"),
    ],
)
def test_heading_variants(heading: str, expected: str) -> None:
    chunks = DecisionSectionChunker().chunk(make_doc(f"{heading}\nText des Abschnitts."))
    assert sections(chunks) == [expected]
    assert chunks[0].text == "Text des Abschnitts."


def test_a_heading_is_the_whole_line_never_a_word_in_a_sentence() -> None:
    text = (
        "Das Tenor der Entscheidung und die Gründe sind klar.\n"
        "Tatbestand\nEs geht um Tenor und Gründe."
    )
    chunks = DecisionSectionChunker().chunk(make_doc(text))
    assert sections(chunks) == [None, "Tatbestand"]


def test_text_before_the_first_heading_is_a_section_none_chunk() -> None:
    chunks = DecisionSectionChunker().chunk(make_doc("Im Namen des Volkes\nTenor\nAbgewiesen."))
    assert sections(chunks) == [None, "Tenor"]
    assert chunks[0].text == "Im Namen des Volkes"


def test_verfahrensgang_ends_a_section_but_is_not_one() -> None:
    chunks = DecisionSectionChunker().chunk(
        make_doc(
            "Tenor\nAbgewiesen.\nVerfahrensgang\nvorgehend ArbG Frankfurt\nTatbestand\nStreit."
        )
    )
    assert sections(chunks) == ["Tenor", None, "Tatbestand"]


def test_trailing_apparatus_is_dropped() -> None:
    text = (
        "Tenor\nAbgewiesen.\nDiese Entscheidung zitiert\n"
        "BGH, 1. Januar 2000, I ZR 1/00\nFußnoten\nx"
    )
    chunks = DecisionSectionChunker().chunk(make_doc(text))
    assert sections(chunks) == ["Tenor"]
    assert all("BGH" not in c.text for c in chunks)


def test_no_headings_falls_back_to_fixed_windows_of_512_with_overlap_64() -> None:
    text = "\n".join([PARAGRAPH] * 40)  # 2 600 tokens, no heading line
    doc = make_doc(text)
    assert not has_named_sections(doc.text)
    chunks = DecisionSectionChunker().chunk(doc)
    assert len(chunks) >= 5
    assert all(c.section is None for c in chunks)
    assert all(count_tokens(c.text) <= 512 for c in chunks)
    for first, second in pairwise(chunks):
        assert count_tokens(first.text) == 512
        assert tokens(first.text)[-64:] == tokens(second.text)[:64]  # the 64-token overlap
    assert [c.chunk_id for c in chunks] == [f"oldp-123#{i}" for i in range(len(chunks))]


def test_long_entscheidungsgruende_are_split_and_keep_the_section() -> None:
    body = "\n".join([PARAGRAPH] * 52)  # 3 120 tokens
    assert count_tokens(body) > 3000
    chunks = DecisionSectionChunker().chunk(
        make_doc(f"Tenor\nAbgewiesen.\nEntscheidungsgründe\n{body}")
    )
    gruende = [c for c in chunks if c.section == "Entscheidungsgründe"]
    assert len(gruende) >= 6
    assert len(gruende) == len(chunks) - 1
    assert all(count_tokens(c.text) <= 512 for c in gruende)
    assert [c.chunk_id for c in chunks] == [f"oldp-123#{i}" for i in range(len(chunks))]
    assert "".join(c.text for c in gruende).replace("\n", "").replace(" ", "") == body.replace(
        "\n", ""
    ).replace(" ", "")


def test_chunk_ids_are_stable_across_runs() -> None:
    doc = make_doc(f"Tenor\nX.\nGründe\n{chr(10).join([PARAGRAPH] * 30)}")
    assert DecisionSectionChunker().chunk(doc) == DecisionSectionChunker().chunk(doc)


def test_randnummer_blocks_are_kept_whole_and_start_the_chunks() -> None:
    blocks = [f"{n}\n{PARAGRAPH}\n{PARAGRAPH}\n{PARAGRAPH}" for n in range(1, 13)]  # 181 tokens
    chunks = DecisionSectionChunker().chunk(make_doc("Entscheidungsgründe\n" + "\n".join(blocks)))
    assert len(chunks) == 6  # two blocks (362 tokens) per chunk, a third would exceed 512
    for chunk in chunks:
        assert chunk.text.split("\n")[0].isdigit()
        assert count_tokens(chunk.text) <= 512
    assert [c.text.split("\n")[0] for c in chunks] == ["1", "3", "5", "7", "9", "11"]


def test_a_numbered_list_that_restarts_is_not_a_new_randnummer() -> None:
    text = (
        "Entscheidungsgründe\n1\nErster Absatz.\n2\nZweiter Absatz:\n1\nPunkt eins\n2\nPunkt zwei"
    )
    chunks = DecisionSectionChunker(max_tokens=12, overlap=2).chunk(make_doc(text))
    assert [c.text.split("\n")[0] for c in chunks] == ["1", "2"]
    assert chunks[1].text == "2\nZweiter Absatz:\n1\nPunkt eins\n2\nPunkt zwei"


def test_one_oversized_randnummer_is_cut_into_overlapping_windows() -> None:
    giant = "\n".join([PARAGRAPH] * 20)  # one Randnummer of 1 300 tokens
    chunks = DecisionSectionChunker().chunk(make_doc(f"Gründe\n1\n{giant}\n2\n{PARAGRAPH}"))
    assert all(c.section == "Entscheidungsgründe" for c in chunks)
    assert all(count_tokens(c.text) <= 512 for c in chunks)
    assert len(chunks) >= 4


def test_blank_text_has_no_chunks() -> None:
    assert DecisionSectionChunker().chunk(make_doc("")) == []
    assert DecisionSectionChunker().chunk(make_doc("Tenor\n \nTatbestand\n")) == []


def test_split_sections_reports_the_segments() -> None:
    segments = split_sections("Rubrum\nTenor\nA.\nGründe\nB.")
    assert [(s.section, s.lines) for s in segments] == [
        (None, ["Rubrum"]), ("Tenor", ["A."]), ("Entscheidungsgründe", ["B."]),
    ]  # fmt: skip


def test_real_fixtures_through_the_loader(oldp_raw: Path) -> None:
    docs = {d.doc_id: d for d in OldpLoader().load(oldp_raw)}
    chunker = DecisionSectionChunker()
    labour = chunker.chunk(docs[DocId("oldp-446202")])
    named = [s for s in sections(labour) if s]
    assert named[:1] == ["Tenor"]
    assert {"Tenor", "Tatbestand", "Entscheidungsgründe"} <= set(named)
    assert named.index("Tenor") < named.index("Tatbestand") < named.index("Entscheidungsgründe")
    insurance = chunker.chunk(docs[DocId("oldp-299231")])
    assert {"Tenor", "Tatbestand"} <= set(sections(insurance))  # "T a t b e s t a n d :"
    plain = docs[DocId("oldp-487573")]
    assert not has_named_sections(plain.text)
    assert all(c.section is None for c in chunker.chunk(plain))
    assert all(c.license == "ODbL-1.0" for c in labour + insurance)


def best_of(runs: int, text: str) -> float:
    chunker = DecisionSectionChunker()
    best = float("inf")
    for _ in range(runs):
        start = time.perf_counter()
        chunker.chunk(make_doc(text))
        best = min(best, time.perf_counter() - start)
    return best


def test_time_grows_linearly_with_many_headings_and_randnummern() -> None:
    def build(n: int) -> str:
        return "\n".join(f"Tenor\nText {i}\n{i}\nGründe\nWort Wort Wort" for i in range(n))

    small, large = best_of(3, build(2_000)), best_of(3, build(16_000))
    assert large / small < 20  # linear = 8, quadratic = 64


def test_long_non_heading_lines_are_cheap() -> None:
    start = time.perf_counter()
    DecisionSectionChunker().chunk(make_doc(("G r ü n d e " * 20_000) + "\nTenor\nx"))
    assert time.perf_counter() - start < 5

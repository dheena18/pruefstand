"""The ``evidence_span`` rule (R9 AI9-06, X3.2): verbatim, inside the cited Absatz, <= 60 tokens."""

from testsupport.qa_support import chunk

from pruefstand.dataset.evidence import MAX_EVIDENCE_TOKENS, cited_absatz, evidence_span

TWO_ABS = "(2) Die Frist beträgt einen Monat.\n(3) Während der Probezeit gelten zwei Wochen."


def test_substring_inside_the_cited_absatz_is_kept() -> None:
    c = chunk("gii-bgb-622#1")
    ev = "1. zwei Jahre bestanden hat, einen Monat zum Ende eines Kalendermonats,"
    assert evidence_span(ev, c.text, "2") == ev


def test_whitespace_and_soft_hyphens_are_normalised() -> None:
    c = chunk("gii-bgb-622#1")
    ev = "1. zwei  Jahre\nbestanden hat,­ einen Monat"
    assert evidence_span(ev, c.text, "2") == "1. zwei Jahre bestanden hat, einen Monat"


def test_paraphrase_is_none() -> None:
    c = chunk("gii-bgb-622#1")
    assert evidence_span("Nach zwei Jahren gilt ein Monat.", c.text, "2") is None
    assert evidence_span("", c.text, "2") is None
    assert evidence_span("   ", c.text, "2") is None


def test_span_from_another_absatz_is_none() -> None:
    assert evidence_span("Die Frist beträgt einen Monat.", TWO_ABS, "2") == (
        "Die Frist beträgt einen Monat."
    )
    assert evidence_span("Während der Probezeit gelten zwei Wochen.", TWO_ABS, "2") is None
    assert evidence_span("Während der Probezeit gelten zwei Wochen.", TWO_ABS, "3") is not None


def test_no_absatz_named_accepts_the_whole_chunk() -> None:
    assert evidence_span("Während der Probezeit gelten zwei Wochen.", TWO_ABS, None) is not None


def test_chunk_without_absatz_markers_accepts_any_cited_absatz() -> None:
    text = "1. zwei Jahre bestanden hat, einen Monat zum Ende eines Kalendermonats,"
    assert evidence_span(text, text, "2") == text


def test_a_cited_absatz_that_is_not_in_the_chunk_is_none() -> None:
    assert evidence_span("Die Frist beträgt einen Monat.", TWO_ABS, "7") is None


def test_61_tokens_is_none_and_60_is_kept() -> None:
    words = " ".join(f"wort{i}" for i in range(MAX_EVIDENCE_TOKENS + 1))
    assert evidence_span(words, words, None) is None
    sixty = " ".join(f"wort{i}" for i in range(MAX_EVIDENCE_TOKENS))
    assert evidence_span(sixty, sixty, None) == sixty


def test_cited_absatz_is_read_from_the_citation_of_the_chunks_paragraph() -> None:
    c = chunk("gii-bgb-622#1")
    assert cited_absatz("§ 622 Abs. 2 Nr. 1 BGB", c) == "2"
    assert cited_absatz("§ 622 BGB", c) is None
    assert cited_absatz(None, c) is None
    assert cited_absatz("§ 1 Abs. 3 KSchG und § 622 Abs. 2 BGB", c) == "2"
    assert cited_absatz("§ 1 Abs. 3 KSchG", c) is None

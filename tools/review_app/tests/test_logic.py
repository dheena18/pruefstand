"""The browser-free parts of the review app, on real slice chunks (T4.7a)."""

from review_app.logic import ABSATZ, EVIDENCE, NONE, cited_absaetze, segments_of, source_views
from testsupport.qa_support import slice_chunks

from pruefstand.core.enums import Category, Difficulty, Lang, Split
from pruefstand.core.models.testcase import TestCase

PROBE_EVIDENCE = "Während einer vereinbarten Probezeit, längstens für die Dauer von sechs Monaten"


def _case(citation: str, evidence: str | None = PROBE_EVIDENCE) -> TestCase:
    return TestCase.model_validate(
        {
            "id": "c1", "base_id": "c1", "cluster_id": "gii-bgb-622", "tenant": "shared_public",
            "lang": Lang.DE, "question": "Mit welcher Frist kann man in der Probezeit kündigen?",
            "reference_answer": "Mit zwei Wochen.", "gold_doc_ids": ("gii-bgb-622",),
            "gold_citations": (citation,), "evidence_span": evidence, "category": Category.FACTUAL,
            "difficulty": Difficulty.EASY, "split": Split.SMOKE, "source": "generated",
            "license_config": "laws_eurlex", "corpus_version": "slice",
        }
    )  # fmt: skip


def test_the_cited_absatz_and_its_evidence_are_marked_and_nothing_is_lost() -> None:
    text = "(1) Eins gilt hier.\n(2) Zwei gilt hier, und noch mehr.\n(3) Drei gilt hier."
    segments = segments_of(text, "2", "Zwei gilt hier")
    assert "".join(s.text for s in segments) == text
    assert [(s.text, s.level) for s in segments if s.level] == [
        ("(2) ", ABSATZ), ("Zwei gilt hier", EVIDENCE), (", und noch mehr.\n", ABSATZ),
    ]  # fmt: skip
    assert all(s.level == NONE for s in segments if "(1)" in s.text or "(3)" in s.text)


def test_without_an_absatz_marker_only_the_evidence_is_marked() -> None:
    segments = segments_of("Eins gilt hier und Zwei auch.", None, "Zwei  auch.")
    assert [(s.text, s.level) for s in segments if s.level] == [("Zwei auch.", EVIDENCE)]
    assert "".join(s.text for s in segments) == "Eins gilt hier und Zwei auch."


def test_the_source_view_marks_the_probezeit_absatz_in_the_real_chunk() -> None:
    views = source_views(_case("§ 622 Abs. 3 BGB"), list(slice_chunks().values()))
    marked = {v.chunk_id: [s for s in v.segments if s.level] for v in views}
    assert [cid for cid, segs in marked.items() if segs] == ["gii-bgb-622#2"]
    assert any(s.level == EVIDENCE for s in marked["gii-bgb-622#2"])
    assert len(views) == 6  # every chunk of the paragraph is shown, in order


def test_a_wrong_citation_marks_nothing_but_the_text_stays_visible() -> None:
    views = source_views(_case("§ 623 BGB"), list(slice_chunks().values()))
    assert views
    assert all(s.level == NONE for v in views for s in v.segments)


def test_cited_absaetze_by_provision() -> None:
    assert cited_absaetze(_case("§ 622 Abs. 3 BGB")) == {"622 BGB": {"3"}}
    assert cited_absaetze(_case("§ 3 ArbZG")) == {"3 ArbZG": set()}

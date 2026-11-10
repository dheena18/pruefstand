"""``scripts/closed_book_text.py``: content words, recall and negation words (T4.7b S4)."""

from closed_book_text import content_recall, content_words, negations


def test_kein_forms_fold_and_other_negations_stay() -> None:
    assert negations("kein keine keinen keinem keiner keines") == frozenset({"kein"})
    assert negations("Weder A noch B, nichts, niemandem, nirgends") == {
        "weder", "nichts", "niemand", "nirgends",
    }  # fmt: skip


def test_the_reference_citation_does_not_count_as_content() -> None:
    reference = "Vier Wochen zum Fünfzehnten oder zum Monatsende (§ 622 Abs. 1 BGB)."
    words = content_words(reference)
    assert not {"622", "abs", "bgb"} & words
    assert content_recall(reference, "vier wochen zum fünfzehnten oder monatsende") == 1.0


def test_inflected_forms_match() -> None:
    assert content_words("Kalendermonats") == content_words("Kalendermonat")


def test_a_citation_does_not_eat_the_first_letter_of_the_next_word() -> None:
    words = content_words("Laut § 622 vier Wochen zum Monatsende")
    assert words == content_words("Laut vier Wochen zum Monatsende")
    assert "vier" in content_words("Laut § 622 vier Wochen zum Monatsende")

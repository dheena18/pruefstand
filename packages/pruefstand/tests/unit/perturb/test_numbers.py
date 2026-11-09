"""numbers: German number format to international (T4.4)."""

import numpy as np
import pytest

from pruefstand.perturb.numbers import Numbers

P = Numbers()
RNG = np.random.default_rng(0)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Kosten von 1.000,50 €", "Kosten von 1000.50 EUR"),
        ("Kosten von 2.381 €", "Kosten von 2381 EUR"),
        ("Zinsen von 13,7 %", "Zinsen von 13.7 %"),
        ("Ab 1.000.000 Euro", "Ab 1000000 EUR"),
        ("Es sind 250 € fällig", "Es sind 250 EUR fällig"),
        ("Es sind 250€ fällig", "Es sind 250 EUR fällig"),
        ("Preis: € 99,90", "Preis: EUR 99.90"),
        ("Bis zu 3,5 Prozent", "Bis zu 3.5 Prozent"),
    ],
)
def test_numbers(text: str, expected: str) -> None:
    result = P.apply(text, RNG)
    assert result.text == expected
    assert result.changed


@pytest.mark.parametrize(
    "text",
    [
        "Gilt § 622",
        "Nach § 622 Abs. 2 Nr. 3 BGB",
        "Es sind 999 Tage",
        "Am 03.10.2026 und 1.1.2025",
        "Abs. 2,3 und Nr. 1,2",
        "Nummer 12.345.2026",
        "Version 1.2.3",
    ],
)
def test_unchanged(text: str) -> None:
    result = P.apply(text, RNG)
    assert not result.changed
    assert result.text == text


def test_metadata() -> None:
    assert (P.name, P.uses_llm) == ("numbers", False)


@pytest.mark.parametrize(
    "text",
    [
        "zwischen 1.000 und 5.000 €",
        "1.000-2.000 €",
        "zwischen 2,5 und 3,5 %",
        "1.000 € und 1.000 Mitarbeiter",
        "Abs. 2,3 und 13,7 %",
        "13,375 %",
        "§622",
        "1.1.1.2025",
    ],
)
def test_half_converted_text_is_left_unchanged(text: str) -> None:
    """If any number would stay in German format, the whole text stays (no mixed readings)."""
    result = P.apply(text, RNG)
    assert not result.changed
    assert result.text == text


@pytest.mark.parametrize(
    "text",
    [
        "zwischen ca.1.000 € und 5.000,50 €",
        "ca.2,5 % bis 3,5 %",
        "§1,5 % und 2,5 %",
    ],
)
def test_glued_german_numbers_count_as_leftovers(text: str) -> None:
    result = P.apply(text, RNG)
    assert not result.changed
    assert result.text == text


# --- T4.4a (D891) ---------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Streitwert 10.000,- € netto", "Streitwert 10000 EUR netto"),
        ("Streitwert 10.000,-- €", "Streitwert 10000 EUR"),
        ("Gebühr: 250,- €", "Gebühr: 250 EUR"),
        ("Ein Umsatz von 3,5 Mio. €", "Ein Umsatz von 3.5 Mio. EUR"),
        ("Ein Umsatz von 3,5 Mio. Euro", "Ein Umsatz von 3.5 Mio. EUR"),
        ("rund 2,25 Milliarden Euro", "rund 2.25 Milliarden EUR"),
        ("Es sind 1.000 Euro und 250 €", "Es sind 1000 EUR und 250 EUR"),
        ("Es sind 5 Euro", "Es sind 5 EUR"),
        ("Rechnung über 1 000,50 €", "Rechnung über 1000.50 EUR"),
        ("Rechnung über 1\u00a0000,50 EUR", "Rechnung über 1000.50 EUR"),
        ("Rechnung über 12 345 €", "Rechnung über 12345 EUR"),
    ],
)
def test_amounts_scale_words_and_one_currency_code(text: str, expected: str) -> None:
    result = P.apply(text, RNG)
    assert result.text == expected
    assert result.changed


@pytest.mark.parametrize(
    "text",
    [
        "1234,567 €",  # three decimals read like a German thousands group: ambiguous
        "Es gab 5 100 Fälle und 1 000,50 Fälle",  # space groups need a unit
        "Der Euro ist stabil",  # no number: the word is not a currency amount
        "5 €uro",
        "5 €€",
        "x€ und 5 €",
        "Euro€ 5,50 €",
    ],
)
def test_ambiguous_or_junk_currency_text_is_left_alone(text: str) -> None:
    result = P.apply(text, RNG)
    assert not result.changed
    assert result.text == text


def test_the_converted_text_is_stable() -> None:
    once = P.apply("10.000,- € und 3,5 Mio. € und 1 000,50 €", RNG).text
    assert once == "10000 EUR und 3.5 Mio. EUR und 1000.50 EUR"
    assert not P.apply(once, RNG).changed

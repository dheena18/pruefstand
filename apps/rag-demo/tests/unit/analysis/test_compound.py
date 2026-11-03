"""Dictionary compound splitter: direct calls, no folding, no stemming (T3.3)."""

import json
import re

import pytest
from hypothesis import given
from hypothesis import strategies as st
from rd_support import REPO

from rag_demo.analysis import compound


def test_kuendigungsschutzgesetz_has_three_parts_with_fugen_s() -> None:
    assert compound.split("Kündigungsschutzgesetz") == ["kündigung", "schutz", "gesetz"]


def test_arbeitszeitgesetz_drops_the_fugen_s() -> None:
    assert compound.split("Arbeitszeitgesetz") == ["arbeit", "zeit", "gesetz"]


def test_rahmenvertrag_prefers_the_whole_word_over_stem_plus_fugen() -> None:
    assert compound.split("Rahmenvertrag") == ["rahmen", "vertrag"]


def test_short_word_is_unchanged() -> None:
    assert compound.split("Gesetz") == ["gesetz"]


def test_unknown_long_word_is_unchanged() -> None:
    assert compound.split("Zwiebelmuffelei") == ["zwiebelmuffelei"]


def test_transliterated_spelling_splits_too() -> None:
    assert compound.split("Kuendigungsschutzgesetz") == ["kuendigung", "schutz", "gesetz"]


@pytest.mark.parametrize(
    ("word", "parts"),
    [
        ("Mietvertrag", ["miet", "vertrag"]),
        ("Datenschutzgrundverordnung", ["daten", "schutz", "grund", "verordnung"]),
        ("Gebührenordnung", ["gebühr", "ordnung"]),
        ("Kündigungsfrist", ["kündigung", "frist"]),
    ],
)
def test_legal_compounds(word: str, parts: list[str]) -> None:
    assert compound.split(word) == parts


def test_parts_are_at_least_three_characters() -> None:
    assert all(len(part) >= 3 for part in compound.split("Arbeitnehmerschutzgesetz"))


@given(st.text(max_size=40))
def test_split_is_deterministic_and_never_raises(word: str) -> None:
    assert compound.split(word) == compound.split(word)
    assert compound.split(word)


@pytest.mark.parametrize(
    ("word", "parts"),
    [
        ("Kündigungsfristen", ["kündigung", "frist"]),
        ("Arbeitnehmerüberlassungsgesetz", ["arbeit", "nehmer", "überlassung", "gesetz"]),
        ("Haftpflichtversicherung", ["haft", "pflicht", "versicherung"]),
        ("Versicherungsnehmer", ["versicherung", "nehmer"]),
        ("Steuerberater", ["steuer", "berater"]),
        ("Arbeitsverhältnisses", ["arbeit", "verhältnis"]),
    ],
)
def test_inflected_last_part_is_matched_after_stripping_the_ending(
    word: str, parts: list[str]
) -> None:
    assert compound.split(word) == parts


FIXTURES = REPO / "datasets" / "fixtures" / "slice_v1"
# Hand-labelled words that occur in the fixture questions and answers (checked against the text).
GOLD_COMPOUNDS = {
    "arbeitsbedingungen": ["arbeit", "bedingung"],
    "arbeitsgericht": ["arbeit", "gericht"],
    "arbeitsverhältnis": ["arbeit", "verhältnis"],
    "arbeitsverhältnisses": ["arbeit", "verhältnis"],
    "beschäftigungsverhältnis": ["beschäftigung", "verhältnis"],
    "betriebsrat": ["betrieb", "rat"],
    "datenverarbeitung": ["daten", "verarbeitung"],
    "datenminimierung": ["daten", "minimierung"],
    "dienstverhältnis": ["dienst", "verhältnis"],
    "elternzeit": ["eltern", "zeit"],
    "gebäudeversicherung": ["gebäude", "versicherung"],
    "kündigungsfrist": ["kündigung", "frist"],
    "kündigungsfristen": ["kündigung", "frist"],
    "kündigungsschutzgesetz": ["kündigung", "schutz", "gesetz"],
    "kündigungsberechtigte": ["kündigung", "berechtigte"],
    "rahmenvertrag": ["rahmen", "vertrag"],
    "ruhepausen": ["ruhe", "pause"],
    "urlaubstage": ["urlaub", "tag"],
    "stadtwerke": ["stadt", "werk"],
    "eigenbedarf": ["eigen", "bedarf"],
    "mindestlohn": ["mindest", "lohn"],
    "schriftform": ["schrift", "form"],
}
GOLD_SIMPLE = [
    "abhängigkeit",
    "berücksichtigung",
    "unterbrechung",
    "verarbeitung",
    "einwilligung",
    "feststellung",
    "angemessen",
    "erforderlich",
    "unverzüglich",
    "beschäftigten",
    "interessen",
    "unternehmen",
]


def _fixture_words() -> set[str]:
    words: set[str] = set()
    for name in ("smoke.jsonl", "smoke_live.jsonl"):
        for line in (FIXTURES / name).read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row["lang"] != "de":
                continue
            text = " ".join(str(row.get(k) or "") for k in ("question", "reference_answer"))
            words |= set(re.findall(r"[^\W\d_]{10,}", text.lower()))
    return words


def test_real_fixture_text_split_rate_and_no_false_splits() -> None:
    words = _fixture_words()
    present = {w: parts for w, parts in GOLD_COMPOUNDS.items() if w in words}
    assert len(present) >= 15  # the gold list is tied to the committed fixture text
    wrong = {w: compound.split(w) for w, parts in present.items() if compound.split(w) != parts}
    assert not wrong
    for simple in GOLD_SIMPLE:
        assert compound.split(simple) == [simple]

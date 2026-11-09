"""Dictionary compound splitter: direct calls, no folding, no stemming (T3.3)."""

import json
import re
from pathlib import Path

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


# T3.3a: the RQ1 compound axis. The reviewed file locks every split of the committed corpus and
# fixture text (hand-reviewed); the simple list holds corpus words that must stay whole.
GOLD_FILE = Path(__file__).with_name("compound_gold_de.txt")
CORPUS_FILES = [
    *sorted((REPO / "corpus" / "slice_v1").glob("*.jsonl")),
    *sorted(FIXTURES.glob("*.jsonl")),
]
GOLD_SIMPLE_CORPUS = [
    "verantwortlichen",
    "voraussetzungen",
    "unverhältnismäßig",
    "grundsätzlich",
    "ausdrücklich",
    "vereinbarung",
    "verpflichtung",
    "unterbrechung",
    "einwilligung",
    "entscheidung",
    "beschäftigten",
    "berücksichtigung",
    "gewährleistung",
    "hinsichtlich",
    "insbesondere",
    "regelmäßigen",
    "elektronische",
    "schriftlichen",
    "wesentlich",
    "unverzüglich",
    "zustimmung",
    "verlängerung",
    "rechtmäßigkeit",
    "vertraulichkeit",
]


def _gold() -> dict[str, list[str]]:
    rows = [ln.split() for ln in GOLD_FILE.read_text(encoding="utf-8").splitlines()]
    return {r[0]: r[1].split("+") for r in rows if r and not r[0].startswith("#")}


def _corpus_words() -> set[str]:
    words: set[str] = set()
    for path in CORPUS_FILES:
        words |= set(re.findall(r"[^\W\d_]{10,}", path.read_text(encoding="utf-8").lower()))
    return words


def test_reviewed_split_set_is_unchanged_regression_lock() -> None:
    gold = _gold()
    assert len(gold) >= 100
    missed = {w: compound.split(w) for w, parts in gold.items() if compound.split(w) != parts}
    assert not missed
    in_text = _corpus_words() & set(gold)
    assert len(in_text) / len(gold) >= 0.95  # the gold file is tied to the committed text


def test_every_split_of_the_corpus_is_a_reviewed_gold_split() -> None:
    gold = _gold()
    unreviewed = {
        w: compound.split(w)
        for w in _corpus_words()
        if len(compound.split(w)) > 1 and w not in gold
    }
    assert not unreviewed, "a new split in the corpus text: review it, then add it to the gold file"


def test_precision_simple_corpus_words_stay_whole() -> None:
    assert len(GOLD_SIMPLE_CORPUS) >= 20
    split = {w: compound.split(w) for w in GOLD_SIMPLE_CORPUS if compound.split(w) != [w]}
    assert split == {}


def test_lexicon_stays_small_and_unique() -> None:
    lines = (
        (REPO / "apps/rag-demo/src/rag_demo/analysis/lexicon_de.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert len(lines) == len(set(lines))
    assert lines == sorted(lines)
    assert sum(len(ln.encode("utf-8")) + 1 for ln in lines) < 5 * 1024  # D460


def test_known_misses_file_is_sorted_unique_and_not_in_the_reviewed_set() -> None:
    path = GOLD_FILE.with_name("compound_known_misses_de.txt")
    words = [ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.startswith("#")]
    assert len(words) >= 15
    assert words == sorted(set(words))
    assert not set(words) & set(_gold())

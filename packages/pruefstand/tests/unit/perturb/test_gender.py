"""gender: seeded style choice, rule table for frequent nouns, LLM for singular + article (T4.5)."""

from importlib.resources import files

import numpy as np
import pytest
import yaml
from testsupport.loopback_script import serve_script
from testsupport.perturb_support import JUDGE, REWRITER, answers, client, verdict

from pruefstand.perturb.gender import STYLES, Gender, load_nouns, rule_gender
from pruefstand.perturb.rewriter import Rewriter
from pruefstand.perturb.validate import RewriteValidator

Q = "Wie viele Mitarbeiter braucht der Betrieb?"
FORMS = {
    "Wie viele Mitarbeiter*innen braucht der Betrieb?",
    "Wie viele Mitarbeiter:innen braucht der Betrieb?",
    "Wie viele Mitarbeitende braucht der Betrieb?",
    "Wie viele Mitarbeiterinnen und Mitarbeiter braucht der Betrieb?",
}


def _texts(seeds: range) -> set[str]:
    out = set()
    for s in seeds:
        got = rule_gender(Q, np.random.default_rng(s))
        assert got is not None
        out.add(got.text)
    return out


def test_table_has_at_least_forty_nouns() -> None:
    assert len(load_nouns()) >= 40


def test_one_of_the_four_styles_and_seeded() -> None:
    assert _texts(range(40)) == FORMS
    a = rule_gender(Q, np.random.default_rng(7))
    b = rule_gender(Q, np.random.default_rng(7))
    assert a is not None
    assert b is not None
    assert a.text == b.text
    assert a.variant in STYLES


def test_dative_and_bare_plural() -> None:
    got = rule_gender("Was gilt bei Mitarbeitern und Verbrauchern?", np.random.default_rng(1))
    assert got is not None
    assert not got.needs_llm
    assert "Mitarbeitern" not in got.text
    assert "Verbrauchern" not in got.text


def test_singular_with_article_needs_llm() -> None:
    got = rule_gender("Darf der Mitarbeiter kündigen?", np.random.default_rng(0))
    assert got is not None
    assert got.needs_llm


@pytest.mark.parametrize(
    "q",
    [
        "Wie lang ist die Frist?",
        "Gilt das für Mitarbeiterinnen?",
        "Wie viele Mitarbeiter*innen gibt es?",
    ],
)
def test_not_applicable(q: str) -> None:
    assert rule_gender(q, np.random.default_rng(0)) is None


def test_yaml_entries_are_well_formed() -> None:
    text = files("pruefstand.perturb.data").joinpath("gender_nouns.yaml").read_text("utf-8")
    assert all({"pl", "f_pl"} <= set(e) for e in yaml.safe_load(text)["nouns"])


async def test_llm_handles_singular_and_is_validated() -> None:
    q = "Darf der Mitarbeiter kündigen?"
    with (
        serve_script(answers("Dürfen Mitarbeitende kündigen?")) as (rb, _),
        serve_script(answers(verdict(1))) as (jb, _j),
    ):
        p = Gender(Rewriter(REWRITER), RewriteValidator(client(jb, JUDGE), JUDGE))
        res = await p.aapply(q, client(rb, REWRITER), np.random.default_rng(0))
    assert res.changed
    assert res.text == "Dürfen Mitarbeitende kündigen?"


@pytest.mark.parametrize(
    "q",
    [
        "Muss ich das beim Arbeitgeber melden?",
        "Bekomme ich vom Arbeitgeber Geld?",
        "Darf dein Arbeitgeber das?",
        "Darf der neue Arbeitgeber kündigen?",
        "Gilt das für Ihren Mitarbeiter?",
    ],
)
def test_ambiguous_singular_context_goes_to_the_model(q: str) -> None:
    got = rule_gender(q, np.random.default_rng(0))
    assert got is not None
    assert got.needs_llm
    assert got.text == q


def test_adjective_before_a_plural_noun_is_still_rule_converted() -> None:
    got = rule_gender("Haben die neuen Mitarbeiter Anspruch?", np.random.default_rng(0))
    assert got is not None
    assert not got.needs_llm


@pytest.mark.parametrize(
    "q",
    [
        "Welche Rechte hat ein sehr guter neuer Arbeitgeber?",
        "Kann mein langjähriger, erfahrener Arbeitgeber kündigen?",
        "Muss der für die Lohnzahlung zuständige Arbeitgeber zahlen?",
        "Darf Arbeitgeber Müller kündigen?",
        "Wer ist Arbeitgeber, wenn der Vertrag ruht?",
        "Gilt das für Mitarbeiter?",
    ],
)
def test_ambiguous_noun_is_never_rule_only_without_a_direct_plural_determiner(q: str) -> None:
    got = rule_gender(q, np.random.default_rng(0))
    assert got is None or got.needs_llm


def _partizip(q: str) -> str | None:
    for seed in range(80):
        got = rule_gender(q, np.random.default_rng(seed))
        if got is not None and got.variant == "partizip" and not got.needs_llm:
            return got.text
    return None


@pytest.mark.parametrize(
    ("q", "out"),
    [
        ("Dürfen die Mitarbeiter streiken?", "Dürfen die Mitarbeitenden streiken?"),
        ("Haben alle Mitarbeiter Urlaub?", "Haben alle Mitarbeitenden Urlaub?"),
        ("Gibt es keine Mitarbeiter?", "Gibt es keine Mitarbeitenden?"),
        ("Dürfen die neuen Mitarbeiter streiken?", "Dürfen die neuen Mitarbeitenden streiken?"),
        (
            "Wie viele Mitarbeiter braucht der Betrieb?",
            "Wie viele Mitarbeitende braucht der Betrieb?",
        ),
        ("Gilt das für zwei Mitarbeiter?", "Gilt das für zwei Mitarbeitende?"),
    ],
)
def test_participle_takes_the_declension_of_its_context(q: str, out: str) -> None:
    assert _partizip(q) == out


def test_participle_is_not_used_after_an_unclear_determiner() -> None:
    assert _partizip("Welche Mitarbeiter dürfen streiken?") is None

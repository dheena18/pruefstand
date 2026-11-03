"""Validity check of an LLM rewrite (T4.5 S4, ADR-0019)."""

import pytest
from testsupport.loopback_script import serve_script
from testsupport.perturb_support import (
    JUDGE,
    LOCAL_REWRITER,
    REWRITER,
    SECOND,
    answers,
    client,
    verdict,
)

from pruefstand.core.errors import ConfigError
from pruefstand.perturb.draft import Draft
from pruefstand.perturb.validate import RewriteValidator, static_check

SRC = "Gilt das Kündigungsschutzgesetz für Kleinbetriebe?"


def _draft(
    text: str,
    *,
    name_model: str = REWRITER,
    local: bool = False,
    variant: str = "",
    targets: tuple[str, ...] = (),
) -> Draft:
    return Draft(
        text=text, model=name_model, local=local, used_llm=True, variant=variant, targets=targets
    )


def test_register_du_with_leftover_sie_is_invalid() -> None:
    d = _draft("Kannst du mir sagen, ob Sie arbeiten?", variant="du")
    assert (
        static_check("register", "Können Sie mir sagen, ob Sie arbeiten?", d)
        == "transformation_missing"
    )


def test_register_du_clean_is_valid() -> None:
    d = _draft("Kannst du mir sagen, wann die Frist endet?", variant="du")
    assert static_check("register", "Können Sie mir sagen, wann die Frist endet?", d) is None


def test_new_number_and_paragraph_are_rejected() -> None:
    src = "Wie lange ist die Kündigungsfrist nach § 622 BGB?"
    assert (
        static_check("colloquial", src, _draft("Wie lange muss ich nach 30 Tagen gehen?"))
        == "number_changed"
    )
    assert (
        static_check("colloquial", src, _draft("Wie lange dauert das nach § 623 BGB?"))
        == "number_changed"
    )


def test_gender_needs_a_gender_form() -> None:
    src = "Wie viele Mitarbeiter braucht der Betrieb?"
    assert static_check("gender", src, _draft(src)) is not None
    ok = _draft("Wie viele Mitarbeiter*innen braucht der Betrieb?", variant="star")
    assert static_check("gender", src, ok) is None


def test_question_mark_must_stay() -> None:
    assert (
        static_check("colloquial", SRC, _draft("Gilt das für meine kleine Bude")) == "question_lost"
    )


async def test_score_one_is_valid_and_score_zero_invalid() -> None:
    d = _draft(
        "Gilt das Gesetz zum Schutz vor Kündigungen für Kleinbetriebe?",
        targets=("Kündigungsschutzgesetz",),
    )
    with serve_script(answers(verdict(1), verdict(0, "anderer Sinn"))) as (base, state):
        v = RewriteValidator(client(base, JUDGE), JUDGE)
        assert (await v.judge("compound_split", SRC, d)).valid is True
        bad = await v.judge("compound_split", SRC, d.model_copy(update={"text": d.text + " "}))
    assert bad.valid is False
    assert bad.reason == "not_equivalent"
    assert state.posts() == 2


async def test_same_family_as_rewriter_raises_config_error() -> None:
    d = _draft(
        "Gilt das Gesetz zum Schutz vor Kündigungen für Kleinbetriebe?", name_model=LOCAL_REWRITER
    )
    with serve_script(answers(verdict(1))) as (base, _):
        v = RewriteValidator(client(base, JUDGE), JUDGE)
        with pytest.raises(ConfigError, match="family"):
            await v.judge("compound_split", SRC, d)


async def test_local_public_item_uses_second_model() -> None:
    d = _draft(
        "Gilt das Gesetz zum Schutz vor Kündigungen für Kleinbetriebe?",
        name_model=LOCAL_REWRITER,
        local=True,
    )
    with (
        serve_script(answers(verdict(1))) as (jbase, jstate),
        serve_script(answers(verdict(1))) as (sbase, sstate),
    ):
        v = RewriteValidator(client(jbase, JUDGE), JUDGE, second=(client(sbase, SECOND), SECOND))
        out = await v.judge("compound_split", SRC, d)
    assert out.valid
    assert out.validator == SECOND
    assert jstate.posts() == 0
    assert sstate.posts() == 1


async def test_local_item_without_independent_validator_is_dropped() -> None:
    d = _draft(
        "Gilt das Gesetz zum Schutz vor Kündigungen für Kleinbetriebe?",
        name_model=LOCAL_REWRITER,
        local=True,
    )
    with serve_script(answers(verdict(1))) as (base, state):
        out = await RewriteValidator(client(base, JUDGE), JUDGE).judge("compound_split", SRC, d)
    assert (out.valid, out.reason) == (False, "no_independent_validator")
    assert state.posts() == 0


async def test_cross_check_sample_is_seeded_and_logged() -> None:
    d = _draft("Gilt das Gesetz zum Schutz vor Kündigungen für Kleinbetriebe?")
    with (
        serve_script(answers(*[verdict(1)] * 4)) as (jbase, _),
        serve_script(answers(*[verdict(0)] * 4)) as (sbase, sstate),
    ):
        v = RewriteValidator(
            client(jbase, JUDGE),
            JUDGE,
            second=(client(sbase, SECOND), SECOND),
            cross_check_rate=1.0,
        )
        out = await v.judge("compound_split", SRC, d)
        none = RewriteValidator(
            client(jbase, JUDGE),
            JUDGE,
            second=(client(sbase, SECOND), SECOND),
            cross_check_rate=0.0,
        )
        skipped = await none.judge("compound_split", SRC, d)
    assert out.valid
    assert out.cross_check == 0
    assert skipped.cross_check is None
    assert sstate.posts() == 1

"""register: Sie <-> du, rules first, LLM only for what the rules cannot conjugate (T4.5)."""

import numpy as np
import pytest
from testsupport.loopback_script import serve_script
from testsupport.perturb_support import JUDGE, REWRITER, answers, client, verdict

from pruefstand.perturb.register import Register, rule_register
from pruefstand.perturb.rewriter import Rewriter
from pruefstand.perturb.validate import RewriteValidator

RNG = np.random.default_rng(0)


@pytest.mark.parametrize(
    ("src", "out"),
    [
        (
            "Können Sie mir sagen, wann die Frist endet?",
            "Kannst du mir sagen, wann die Frist endet?",
        ),
        ("Wissen Sie, wann die Frist endet?", "Weißt du, wann die Frist endet?"),
        ("Haben Sie Anspruch auf Urlaub?", "Hast du Anspruch auf Urlaub?"),
        ("Gilt das für Sie?", "Gilt das für dich?"),
        ("Was schulde ich Ihnen?", "Was schulde ich dir?"),
        ("Ist Ihr Vertrag befristet?", "Ist dein Vertrag befristet?"),
    ],
)
def test_sie_to_du_rules(src: str, out: str) -> None:
    got = rule_register(src)
    assert got is not None
    assert got.text == out
    assert got.variant == "du"
    assert not got.needs_llm


def test_du_to_sie_rules() -> None:
    got = rule_register("Kannst du mir sagen, wann die Frist endet?")
    assert got is not None
    assert got.text == "Können Sie mir sagen, wann die Frist endet?"
    assert got.variant == "sie"


def test_subordinate_clause_needs_the_llm() -> None:
    got = rule_register("Ich möchte wissen, ob Sie Anspruch auf Urlaub haben?")
    assert got is not None
    assert got.needs_llm
    assert got.variant == "du"


def test_no_marker_is_not_applicable() -> None:
    assert rule_register("Wie lange ist die Kündigungsfrist?") is None


async def test_rule_only_makes_zero_llm_calls() -> None:
    q = "Können Sie mir sagen, wann die Frist endet?"
    with serve_script(answers("x")) as (rb, rs):
        res = await Register(Rewriter(REWRITER), None).aapply(q, client(rb, REWRITER), RNG)
    assert (res.changed, res.text) == (True, "Kannst du mir sagen, wann die Frist endet?")
    assert rs.posts() == 0


async def test_llm_conjugates_what_the_rules_cannot() -> None:
    q = "Ich möchte wissen, ob Sie Anspruch auf Urlaub haben?"
    want = "Ich möchte wissen, ob du Anspruch auf Urlaub hast?"
    with serve_script(answers(want)) as (rb, rs), serve_script(answers(verdict(1))) as (jb, _):
        p = Register(Rewriter(REWRITER), RewriteValidator(client(jb, JUDGE), JUDGE))
        res = await p.aapply(q, client(rb, REWRITER), RNG)
    assert (res.changed, res.text) == (True, want)
    assert rs.posts() == 1


async def test_llm_leaving_sie_is_invalid() -> None:
    q = "Ich möchte wissen, ob Sie Anspruch auf Urlaub haben?"
    with serve_script(answers("Ich möchte wissen, ob Sie Anspruch auf Urlaub hast?")) as (rb, _):
        p = Register(Rewriter(REWRITER), RewriteValidator(client(rb, JUDGE), JUDGE))
        res = await p.aapply(q, client(rb, REWRITER), RNG)
    assert res.changed is False
    assert res.text == q
    assert "transformation_missing" in res.notes


@pytest.mark.parametrize(
    "src",
    [
        "Können Sie mir sagen, ob die Frist für sie gilt?",
        "Können Sie gegen sie klagen?",
        "Müssen Sie sich arbeitslos melden?",
        "Erinnerst du dich an die Frist?",
    ],
)
def test_lowercase_sie_and_sich_go_to_the_model(src: str) -> None:
    got = rule_register(src)
    assert got is not None
    assert got.needs_llm
    assert got.text == src


@pytest.mark.parametrize(
    "src",
    [
        "Ihnen steht Urlaub zu, oder?",
        "Haben Sie und Ihr Mann Anspruch auf Urlaub?",
        "Er fragte: \u201eKönnen Sie mir helfen?\u201c",
    ],
)
def test_ambiguous_forms_go_to_the_model(src: str) -> None:
    got = rule_register(src)
    assert got is not None
    assert got.needs_llm

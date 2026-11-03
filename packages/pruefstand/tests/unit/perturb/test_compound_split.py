"""compound_split: rule step finds compounds, the rewrite model paraphrases (T4.5)."""

import numpy as np
from testsupport.loopback_script import serve_script
from testsupport.perturb_support import JUDGE, REWRITER, answers, client, verdict

from pruefstand.perturb.compound_split import CompoundSplit, find_compounds
from pruefstand.perturb.rewriter import Rewriter
from pruefstand.perturb.validate import RewriteValidator

RNG = np.random.default_rng(0)


def test_find_compounds_needs_ten_chars_and_a_known_head() -> None:
    assert find_compounds("Gilt das Kündigungsschutzgesetz für Kleinbetriebe?") == (
        "Kündigungsschutzgesetz",
    )
    assert find_compounds("Wie lang ist die Frist für den Vertrag?") == ()
    assert find_compounds("Gilt das Arbeitszeitgesetz und das Arbeitszeitgesetz?") == (
        "Arbeitszeitgesetz",
    )


async def test_rewrite_is_validated_and_accepted() -> None:
    q = "Gilt das Kündigungsschutzgesetz für Kleinbetriebe?"
    want = "Gilt das Gesetz zum Schutz vor Kündigungen für Kleinbetriebe?"
    with serve_script(answers(want)) as (rb, rs), serve_script(answers(verdict(1))) as (jb, js):
        p = CompoundSplit(Rewriter(REWRITER), RewriteValidator(client(jb, JUDGE), JUDGE))
        res = await p.aapply(q, client(rb, REWRITER), RNG)
    assert (res.changed, res.text) == (True, want)
    assert "Kündigungsschutzgesetz" in str(rs.seen[0].body["messages"])
    assert rs.posts() == 1
    assert js.posts() == 1


async def test_no_long_compound_makes_no_llm_call() -> None:
    q = "Wie lange ist die Frist?"
    with serve_script(answers("x")) as (rb, rs):
        p = CompoundSplit(Rewriter(REWRITER), None)
        res = await p.aapply(q, client(rb, REWRITER), RNG)
    assert (res.changed, res.text) == (False, q)
    assert rs.posts() == 0


async def test_model_keeps_compound_means_unchanged() -> None:
    q = "Gilt der Rahmenvertrag für Kleinbetriebe?"
    with serve_script(answers(q)) as (rb, _):
        p = CompoundSplit(Rewriter(REWRITER), None)
        res = await p.aapply(q, client(rb, REWRITER), RNG)
    assert res.changed is False
    assert "unchanged" in res.notes

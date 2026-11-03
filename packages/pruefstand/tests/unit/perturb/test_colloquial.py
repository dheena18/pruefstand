"""colloquial: LLM only; accepted when the equivalence check says 1, new numbers rejected (T4.5)."""

import numpy as np
from testsupport.loopback_script import serve_script
from testsupport.perturb_support import JUDGE, REWRITER, answers, client, verdict

from pruefstand.perturb.colloquial import Colloquial
from pruefstand.perturb.rewriter import Rewriter
from pruefstand.perturb.validate import RewriteValidator

Q = "Unter welchen Voraussetzungen ist eine ordentliche Kündigung durch den Arbeitgeber zulässig?"
RNG = np.random.default_rng(0)


async def test_accepted_with_score_one() -> None:
    out = "Wann darf mein Chef mich rauswerfen?"
    with serve_script(answers(out)) as (rb, _), serve_script(answers(verdict(1))) as (jb, js):
        p = Colloquial(Rewriter(REWRITER), RewriteValidator(client(jb, JUDGE), JUDGE))
        res = await p.aapply(Q, client(rb, REWRITER), RNG)
    assert (res.changed, res.text) == (True, out)
    assert js.posts() == 1


async def test_new_number_is_rejected_without_the_equivalence_call() -> None:
    with (
        serve_script(answers("Darf mich mein Chef nach 30 Tagen rauswerfen?")) as (rb, _),
        serve_script(answers(verdict(1))) as (jb, js),
    ):
        p = Colloquial(Rewriter(REWRITER), RewriteValidator(client(jb, JUDGE), JUDGE))
        res = await p.aapply(Q, client(rb, REWRITER), RNG)
    assert res.changed is False
    assert res.text == Q
    assert "number_changed" in res.notes
    assert js.posts() == 0


async def test_equivalence_zero_rejects() -> None:
    with (
        serve_script(answers("Wann darf mein Chef mich rauswerfen?")) as (rb, _),
        serve_script(answers(verdict(0, "Sinn verändert"))) as (jb, _j),
    ):
        p = Colloquial(Rewriter(REWRITER), RewriteValidator(client(jb, JUDGE), JUDGE))
        res = await p.aapply(Q, client(rb, REWRITER), RNG)
    assert res.changed is False
    assert "not_equivalent" in res.notes

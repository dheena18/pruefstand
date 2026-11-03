"""perturb_case_async: id scheme, kept ids, None when rejected or the client fails (D9-31)."""

import logging

import numpy as np
import pytest
from testsupport.loopback_script import Step, serve_script
from testsupport.perturb_support import JUDGE, REWRITER, answers, client, verdict
from unit.perturb.test_perturb_case import base_case

from pruefstand.core.errors import DatasetError
from pruefstand.perturb.compound_split import CompoundSplit
from pruefstand.perturb.registry import perturb_case_async
from pruefstand.perturb.rewriter import Rewriter
from pruefstand.perturb.validate import RewriteValidator

Q = "Gilt das Kündigungsschutzgesetz für Kleinbetriebe?"
OUT = "Gilt das Gesetz zum Schutz vor Kündigungen für Kleinbetriebe?"


async def test_ids_and_gold_fields_kept() -> None:
    case = base_case(Q)
    with serve_script(answers(OUT)) as (rb, _), serve_script(answers(verdict(1))) as (jb, _j):
        p = CompoundSplit(Rewriter(REWRITER), RewriteValidator(client(jb, JUDGE), JUDGE))
        out = await perturb_case_async(case, p, client(rb, REWRITER), np.random.default_rng(0))
    assert out is not None
    assert out.id == "law-0042~compound_split"
    assert out.base_id == "law-0042"
    assert out.cluster_id == case.cluster_id == "bgb-622"
    assert out.perturbation == "compound_split"
    assert out.question == OUT
    assert out.gold_doc_ids == case.gold_doc_ids
    assert out.reference_answer == case.reference_answer


async def test_equivalence_zero_returns_none() -> None:
    with serve_script(answers(OUT)) as (rb, _), serve_script(answers(verdict(0))) as (jb, _j):
        p = CompoundSplit(Rewriter(REWRITER), RewriteValidator(client(jb, JUDGE), JUDGE))
        rng = np.random.default_rng(0)
        assert await perturb_case_async(base_case(Q), p, client(rb, REWRITER), rng) is None


async def test_llm_error_returns_none_and_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    with serve_script([Step(500)]) as (rb, _):
        p = CompoundSplit(Rewriter(REWRITER), None)
        rng = np.random.default_rng(0)
        assert await perturb_case_async(base_case(Q), p, client(rb, REWRITER), rng) is None
    assert "perturb_llm_error" in caplog.text


async def test_already_perturbed_case_is_refused() -> None:
    case = base_case(Q, id="law-0042~dates", perturbation="dates")
    p = CompoundSplit(Rewriter(REWRITER), None)
    with serve_script([]) as (rb, _), pytest.raises(DatasetError):
        await perturb_case_async(case, p, client(rb, REWRITER), np.random.default_rng(0))

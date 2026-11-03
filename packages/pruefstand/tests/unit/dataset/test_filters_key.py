"""Verdict keys of the support check: nothing stale is reused (T4.3, D829)."""

import json
from collections.abc import Sequence

import numpy as np
import pytest
from numpy.typing import NDArray
from testsupport.loopback_script import Step
from testsupport.qa_support import DATAGEN, SECOND, chunk, datagen_server, make_client

from pruefstand.core.models.dataset import FilterConfig, FilterResult, QACandidate
from pruefstand.dataset.filters_run import SupportSetup, filter_candidates
from pruefstand.dataset.filters_support import support_key

G1 = chunk("gii-bgb-622#1")
CHUNKS = {c.chunk_id: c for c in (G1, chunk("gii-arbzg-3#0"))}


def _cand(question: str) -> QACandidate:
    return QACandidate(
        question=question,
        answer="Einen Monat zum Ende eines Kalendermonats.",
        citation="§ 622 Abs. 2 BGB",
        chunk_id=G1.chunk_id,
        prompt_version="qa_factual_de_v1",
        evidence_span="1. zwei Jahre bestanden hat, einen Monat zum Ende eines Kalendermonats,",
    )


def _verdict(score: int) -> str:
    return json.dumps({"reason": "x", "score": score})


def embed_one(texts: Sequence[str]) -> NDArray[np.float32]:
    return np.ones((len(texts), 2), dtype=np.float32)


def test_a_verdict_key_changes_with_answer_chunk_text_prompt_and_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c = _cand("Wie lange vorher?")
    base = support_key(c, [G1], SECOND)
    assert support_key(c, [G1], SECOND) == base
    assert support_key(c.model_copy(update={"answer": "Zwei Monate."}), [G1], SECOND) != base
    edited = G1.model_copy(update={"text": G1.text + " Neu."})
    assert support_key(c, [edited], SECOND) != base
    assert support_key(c, [G1], DATAGEN) != base
    monkeypatch.setattr("pruefstand.dataset.filters_support.prompt_fingerprint", lambda: "x:1")
    assert support_key(c, [G1], SECOND) != base


async def test_a_changed_answer_or_chunk_is_judged_again_not_reused() -> None:
    c = _cand("Wie lange vorher muss mir mein Chef kündigen?")
    known = {support_key(c, [G1], SECOND): FilterResult(kept=True, reasons=())}
    changed = c.model_copy(update={"answer": "Drei Monate zum Quartal."})
    with datagen_server(_verdict(0)) as (base, state):
        client, _ = make_client(base, model=SECOND)
        setup = SupportSetup(client, SECOND, DATAGEN, known=known)
        out = await filter_candidates([c, changed], CHUNKS, embed_one, support=setup)
        assert state.posts() == 1  # only the changed answer is sent
    assert out.report.reasons == {"unsupported": 1}
    assert out.report.complete


async def test_after_a_quota_every_candidate_is_kept_dropped_or_not_checked_once() -> None:
    cands = [_cand(f"Frage Nummer {i}?") for i in range(6)]
    for concurrency in (1, 4):  # with 4 requests in flight the split varies, the invariant not
        with datagen_server(_verdict(1), [Step(429, {"Retry-After": "86400"})]) as (base, _):
            client, _ = make_client(base, model=SECOND)
            setup = SupportSetup(client, SECOND, DATAGEN)
            out = await filter_candidates(
                cands, CHUNKS, lambda t: np.eye(len(t), dtype=np.float32),
                FilterConfig(concurrency=concurrency), support=setup,
            )  # fmt: skip
        report = out.report
        assert report.kept + report.dropped + report.not_checked == report.total == 6
        assert report.not_checked == len(out.unjudged) >= 1
        assert not report.complete
        assert not {id(c) for c in out.kept} & {id(c) for c in out.unjudged}

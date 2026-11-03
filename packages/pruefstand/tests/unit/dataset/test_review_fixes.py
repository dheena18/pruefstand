"""Regression tests of the #73 review: language, cross-check, prompts, evidence."""

import json
import re
from pathlib import Path

import numpy as np
import pytest
from testsupport.loopback_script import Step
from testsupport.qa_support import (
    DATAGEN,
    SECOND,
    chunk,
    datagen_server,
    make_client,
    reply,
    slice_chunks,
)

from pruefstand.core.ids import ChunkId
from pruefstand.core.models.dataset import QACandidate
from pruefstand.dataset.cross_check import CrossCheckPlan, cross_check
from pruefstand.dataset.evidence import cites_chunk
from pruefstand.dataset.generate import GenStats, generate_qa
from pruefstand.dataset.generate_units import PROMPT_ROOT
from pruefstand.dataset.sampling import sample_chunks, sample_multi_hop_pairs

SIX = 6


def test_single_chunk_sampling_takes_german_chunks_only() -> None:
    pool = list(slice_chunks().values())
    for seed in range(10):
        got = sample_chunks(pool, 50, np.random.default_rng(seed))
        assert got
        assert {c.lang.value for c in got} == {"de"}
        pairs = sample_multi_hop_pairs(pool, 50, np.random.default_rng(seed))
        assert {c.lang.value for p in pairs for c in p} <= {"de"}


def _grams(text: str) -> set[tuple[str, ...]]:
    words = re.findall(r"\w+", text.lower())
    return {tuple(words[i : i + SIX]) for i in range(len(words) - SIX + 1)}


def _examples(path: Path) -> list[tuple[str, dict[str, str]]]:
    user = path.read_text("utf-8").split("### user")[1].split("Jetzt dein Auftrag.")[0]
    out = []
    for block in re.split(r"\nBeispiel[^\n]*\n", user)[1:]:
        source, _, answer = block.partition("\nAntwort:\n")
        out.append((source, json.loads(answer.strip().splitlines()[0])))
    return out


@pytest.mark.parametrize("path", sorted(PROMPT_ROOT.glob("qa_*_de_v1.txt")), ids=lambda p: p.stem)
def test_few_shot_answers_do_not_copy_six_word_runs_from_their_source(path: Path) -> None:
    if path.stem == "qa_validate_de_v1":
        return
    examples = _examples(path)
    assert examples
    for source, obj in examples:
        for field in ("question", "answer"):
            assert not _grams(obj[field]) & _grams(source), (path.stem, field)


async def test_a_cross_check_without_second_answers_counts_nothing() -> None:
    cand = QACandidate(
        question="Frage?", answer="A.", citation="§ 622 BGB", chunk_id=ChunkId("gii-bgb-622#1"),
        prompt_version="qa_factual_de_v1",
    )  # fmt: skip
    stats = GenStats()
    with datagen_server(steps=[Step(429, {"Retry-After": "86400"})]) as (base, _s):
        client, _ = make_client(base, model=SECOND)
        rows = await cross_check(
            [cand], {"gii-bgb-622#1": chunk("gii-bgb-622#1")}, client,
            CrossCheckPlan(model=SECOND, primary_model=DATAGEN, fraction=1.0),
            np.random.default_rng(1), stats=stats,
        )  # fmt: skip
    assert rows[0].second is None
    assert stats.counts["cross_checked"] == 0
    assert stats.counts["quota_exhausted"] == 1


def test_cites_chunk_rejects_a_citation_of_another_paragraph() -> None:
    c = chunk("gii-bgb-622#1")
    assert cites_chunk("§ 622 Abs. 2 BGB", c)
    assert cites_chunk(None, c)
    assert not cites_chunk("§ 1 KSchG", c)


async def test_evidence_of_a_chunk_the_citation_does_not_name_is_invalid() -> None:
    stats = GenStats()
    with datagen_server(reply(citation="§ 1 Abs. 2 KSchG")) as (base, _s):
        client, _ = make_client(base)
        got = await generate_qa(
            [chunk("gii-bgb-622#1")], client, DATAGEN, "qa_factual_de_v1",
            np.random.default_rng(7), stats=stats,
        )  # fmt: skip
    assert got[0].evidence_span is None
    assert stats.counts["evidence_invalid"] == 1

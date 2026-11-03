"""``generate_qa_pairs`` (T4.2 S3): multi-hop and cross-lingual pairs, licence rules."""

import json

import numpy as np
import pytest
from testsupport.loopback import completion_json
from testsupport.loopback_script import Step
from testsupport.qa_support import (
    DATAGEN,
    as_chunk,
    chunk,
    datagen_server,
    make_client,
    reply,
    sent_text,
)

from pruefstand.core.errors import ConfigError
from pruefstand.dataset.generate import GenStats, generate_qa, generate_qa_pairs

MULTI = "qa_multi_hop_de_v1"
CROSS = "qa_cross_lingual_de_v1"
EVIDENCE = "1. zwei Jahre bestanden hat, einen Monat zum Ende eines Kalendermonats,"


def _rng(seed: int = 7) -> np.random.Generator:
    return np.random.default_rng(seed)


def _pair_reply() -> str:
    return reply(
        question="Muss mein Chef eine Frist einhalten, wenn er mir nach zwei Jahren kündigt?",
        citation="§ 622 Abs. 2 BGB; § 1 Abs. 2 KSchG",
        evidence=EVIDENCE,
    )


async def test_one_candidate_per_multi_hop_pair_with_both_chunk_ids() -> None:
    pair = (chunk("gii-bgb-622#1"), chunk("gii-kschg-1#1"))
    with datagen_server(_pair_reply()) as (base, state):
        client, _ = make_client(base)
        got = await generate_qa_pairs([pair], client, DATAGEN, MULTI, _rng())
    assert len(got) == 1
    cand = got[0]
    assert (cand.chunk_id, cand.extra_chunk_ids) == ("gii-bgb-622#1", ("gii-kschg-1#1",))
    assert cand.prompt_version == MULTI
    assert cand.evidence_span == EVIDENCE
    text = sent_text(state)
    assert pair[0].text.split("\n")[0] in text
    assert pair[1].text.split("\n")[0] in text


async def test_invalid_then_valid_pair_answer_is_repaired_once() -> None:
    pair = (chunk("gii-bgb-622#1"), chunk("gii-kschg-1#1"))
    steps = [Step(200, body=completion_json('{"question": '))]
    with datagen_server(_pair_reply(), steps) as (base, state):
        client, _ = make_client(base)
        got = await generate_qa_pairs([pair], client, DATAGEN, MULTI, _rng())
    assert len(got) == 1
    assert state.posts() == 2


async def test_cross_lingual_pair_keeps_both_languages_and_asks_in_both_directions() -> None:
    de, en = chunk("eurlex-32016r0679-art-6-de#0"), chunk("eurlex-32016r0679-art-6-en#0")
    langs = set()
    for seed in range(8):
        with datagen_server(reply(citation="Art. 6 Abs. 1 DSGVO", evidence="x")) as (base, state):
            client, _ = make_client(base)
            got = await generate_qa_pairs([(de, en)], client, DATAGEN, CROSS, _rng(seed))
        cand = got[0]
        langs.add(cand.lang.value)
        assert {cand.chunk_id, *cand.extra_chunk_ids} == {de.chunk_id, en.chunk_id}
        gold = de if cand.lang.value == "en" else en
        assert cand.chunk_id == gold.chunk_id
        assert ("Englisch" if cand.lang.value == "en" else "Deutsch") in sent_text(state)
    assert langs == {"de", "en"}


async def test_license_mixing_pair_is_dropped_before_any_call() -> None:
    base_chunk = chunk("gii-bgb-622#1")
    quad = as_chunk(base_chunk, source="germanquad:train", doc_id="gq-1", chunk_id="gq-1#0")
    oldp = as_chunk(base_chunk, source="oldp:decisions", doc_id="oldp-5", chunk_id="oldp-5#0")
    stats = GenStats()
    with datagen_server(_pair_reply()) as (base, state):
        client, _ = make_client(base)
        got = await generate_qa_pairs([(quad, oldp)], client, DATAGEN, MULTI, _rng(), stats=stats)
    assert got == []
    assert state.posts() == 0
    assert stats.counts["license_mixed"] == 1


async def test_pair_with_a_private_chunk_is_never_sent() -> None:
    pair = (chunk("gii-bgb-622#1"), chunk("syn-km-kanzleihandbuch#0"))
    stats = GenStats()
    with datagen_server(_pair_reply()) as (base, state):
        client, _ = make_client(base)
        got = await generate_qa_pairs([pair], client, DATAGEN, MULTI, _rng(), stats=stats)
    assert got == []
    assert state.posts() == 0
    assert stats.counts["skipped_private"] == 1


async def test_the_prompt_kind_must_match_the_function() -> None:
    pair = (chunk("gii-bgb-622#1"), chunk("gii-kschg-1#1"))
    with datagen_server() as (base, _state):
        client, _ = make_client(base)
        with pytest.raises(ConfigError, match="pair"):
            await generate_qa_pairs([pair], client, DATAGEN, "qa_factual_de_v1", _rng())
        with pytest.raises(ConfigError, match="single"):
            await generate_qa([pair[0]], client, DATAGEN, MULTI, _rng())


def test_pair_reply_helper_is_valid_json() -> None:
    assert json.loads(_pair_reply())["style"] == "laie"

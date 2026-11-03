"""``generate_qa`` (T4.2 S3): single-chunk categories through the real client and backend.

The answers come from the scripted loopback server (plumbing only); real recordings of the
datagen model are made by ``make cassettes`` (``record_cassettes.sh``, dataset section).
"""

import json

import numpy as np
from testsupport.llm_scenarios import DictCache
from testsupport.loopback import completion_json
from testsupport.loopback_script import Step
from testsupport.qa_support import DATAGEN, chunk, datagen_server, make_client, reply, sent_text

from pruefstand.dataset.generate import GenStats, generate_qa

BGB622 = "gii-bgb-622#1"


def _rng() -> np.random.Generator:
    return np.random.default_rng(7)


async def test_recorded_style_answer_becomes_one_candidate() -> None:
    stats = GenStats()
    with datagen_server() as (base, _state):
        client, _ = make_client(base)
        got = await generate_qa(
            [chunk(BGB622)], client, DATAGEN, "qa_factual_de_v1", _rng(), stats=stats
        )
    assert len(got) == 1
    cand = got[0]
    assert cand.prompt_version == "qa_factual_de_v1"
    assert cand.chunk_id == BGB622
    assert cand.citation == "§ 622 Abs. 2 Nr. 1 BGB"
    assert cand.answer == "Einen Monat zum Ende eines Kalendermonats."
    assert (
        cand.evidence_span
        == "1. zwei Jahre bestanden hat, einen Monat zum Ende eines Kalendermonats,"
    )
    assert cand.style == "laie"
    assert stats.counts["candidates"] == 1


async def test_an_invented_evidence_is_dropped_and_counted_not_repaired() -> None:
    stats = GenStats()
    with datagen_server(reply(evidence="Ein Monat gilt nach zwei Jahren.")) as (base, _s):
        client, _ = make_client(base)
        got = await generate_qa(
            [chunk(BGB622)], client, DATAGEN, "qa_factual_de_v1", _rng(), stats=stats
        )
    assert got[0].evidence_span is None
    assert stats.counts["evidence_invalid"] == 1


async def test_invalid_then_valid_is_repaired_with_one_extra_call() -> None:
    steps = [Step(200, body=completion_json('{"question": "Wie lange'))]
    stats = GenStats()
    with datagen_server(steps=steps) as (base, state):
        client, _ = make_client(base)
        got = await generate_qa(
            [chunk(BGB622)], client, DATAGEN, "qa_factual_de_v1", _rng(), stats=stats
        )
    assert len(got) == 1
    assert state.posts() == 2
    assert stats.counts["invalid"] == 0


async def test_invalid_twice_skips_the_candidate_and_counts_it() -> None:
    steps = [
        Step(200, body=completion_json("kein json")),
        Step(200, body=completion_json("immer noch nicht")),
    ]
    stats = GenStats()
    with datagen_server(steps=steps) as (base, _state):
        client, _ = make_client(base)
        got = await generate_qa(
            [chunk(BGB622), chunk("gii-bgb-626#0")],
            client,
            DATAGEN,
            "qa_factual_de_v1",
            _rng(),
            stats=stats,
            concurrency=1,
        )
    assert [c.chunk_id for c in got] == ["gii-bgb-626#0"]
    assert stats.counts["invalid"] == 1


async def test_rendered_prompt_has_the_chunk_text_and_no_tenant_id() -> None:
    c = chunk(BGB622)
    with datagen_server() as (base, state):
        client, _ = make_client(base)
        await generate_qa([c], client, DATAGEN, "qa_factual_de_v1", _rng())
    text = sent_text(state)
    assert c.text.split("\n")[0] in text
    assert c.tenant not in text
    assert "kanzlei" not in text.lower()


async def test_few_shot_examples_hold_no_corpus_document_ids() -> None:
    with datagen_server() as (base, state):
        client, _ = make_client(base)
        await generate_qa([chunk(BGB622)], client, DATAGEN, "qa_factual_de_v1", _rng())
    text = sent_text(state)
    assert "gii-" not in text
    assert "eurlex-" not in text
    assert "Mietrecht" in text or "Miete" in text


async def test_same_seed_sends_the_same_requests() -> None:
    pool = [chunk(BGB622), chunk("gii-bgb-626#0"), chunk("gii-bgb-621#0")]
    bodies = []
    for _ in range(2):
        with datagen_server() as (base, state):
            client, _ = make_client(base)
            await generate_qa(pool, client, DATAGEN, "qa_factual_de_v1", _rng(), concurrency=1)
        bodies.append(
            json.dumps([s.body for s in state.seen if s.method == "POST"], sort_keys=True)
        )
    assert bodies[0] == bodies[1]


async def test_layperson_style_is_requested_for_most_units() -> None:
    pool = [chunk(BGB622), chunk("gii-bgb-626#0"), chunk("gii-bgb-621#0")] * 20
    with datagen_server() as (base, state):
        client, _ = make_client(base)
        await generate_qa(pool, client, DATAGEN, "qa_factual_de_v1", _rng(), concurrency=1)
    task = [sent_text(state, i).split("Jetzt dein Auftrag.")[1] for i in range(state.posts())]
    laie = sum("Stil: laie" in t for t in task)
    assert laie / state.posts() >= 0.6


async def test_cache_serves_a_second_run_without_a_new_request() -> None:
    cache = DictCache()
    pool = [chunk(BGB622), chunk("gii-bgb-626#0")]
    with datagen_server() as (base, state):
        client, _ = make_client(base, cache=cache)
        first = await generate_qa(pool, client, DATAGEN, "qa_factual_de_v1", _rng(), concurrency=1)
        posts = state.posts()
        second = await generate_qa(pool, client, DATAGEN, "qa_factual_de_v1", _rng(), concurrency=1)
    assert first == second
    assert state.posts() == posts


async def test_request_cap_stops_cleanly_and_a_rerun_continues_from_the_ledger() -> None:
    pool = [chunk(BGB622), chunk("gii-bgb-626#0"), chunk("gii-bgb-621#0"), chunk("gii-bgb-620#0")]
    stats = GenStats()
    done: set[str] = set()
    with datagen_server() as (base, state):
        capped, _ = make_client(base, max_requests=2)
        part = await generate_qa(
            pool,
            capped,
            DATAGEN,
            "qa_factual_de_v1",
            _rng(),
            stats=stats,
            concurrency=1,
            sink=lambda key, cand: done.add(key),
        )
        assert len(part) == 2
        assert stats.counts["budget_exceeded"] == 1
        assert state.posts() == 2
        open_client, _ = make_client(base)
        rest = await generate_qa(
            pool, open_client, DATAGEN, "qa_factual_de_v1", _rng(), concurrency=1, skip=done
        )
    assert len(rest) == 2
    assert state.posts() == 4


async def test_daily_quota_stops_the_batch() -> None:
    steps = [Step(429, {"Retry-After": "86400"})]
    stats = GenStats()
    with datagen_server(steps=steps) as (base, state):
        client, _ = make_client(base)
        got = await generate_qa(
            [chunk(BGB622), chunk("gii-bgb-626#0")],
            client,
            DATAGEN,
            "qa_factual_de_v1",
            _rng(),
            stats=stats,
            concurrency=1,
        )
    assert got == []
    assert stats.counts["quota_exhausted"] == 1
    assert state.posts() == 1


async def test_units_in_skip_are_not_requested_but_keep_the_seed_stream() -> None:
    pool = [chunk(BGB622), chunk("gii-bgb-626#0")]
    with datagen_server() as (base, state):
        client, _ = make_client(base)
        await generate_qa(pool, client, DATAGEN, "qa_factual_de_v1", _rng(), concurrency=1)
        full = [s.body for s in state.seen if s.method == "POST"]
    with datagen_server() as (base, state):
        client, _ = make_client(base)
        done = {f"qa_factual_de_v1|{DATAGEN}|{BGB622}"}
        await generate_qa(
            pool, client, DATAGEN, "qa_factual_de_v1", _rng(), concurrency=1, skip=done
        )
        resumed = [s.body for s in state.seen if s.method == "POST"]
    assert resumed == full[1:]


async def test_sink_sees_every_finished_unit_with_its_key() -> None:
    seen: list[tuple[str, bool]] = []
    with datagen_server() as (base, _state):
        client, _ = make_client(base)
        await generate_qa(
            [chunk(BGB622)],
            client,
            DATAGEN,
            "qa_factual_de_v1",
            _rng(),
            sink=lambda key, cand: seen.append((key, cand is not None)),
        )
    assert seen == [(f"qa_factual_de_v1|{DATAGEN}|{BGB622}", True)]

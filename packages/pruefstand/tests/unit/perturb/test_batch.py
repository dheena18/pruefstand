"""Resumable, quota-aware rewrite and validate passes (T4.5, ADR-0019 two passes)."""

from pathlib import Path

import pytest
from testsupport.llm_scenarios import DictCache
from testsupport.loopback_script import Step, serve_script
from testsupport.perturb_support import JUDGE, REWRITER, answers, client, verdict

from pruefstand.core.errors import DatasetError, LLMError
from pruefstand.perturb.batch import Item, RewriteStore, item_id, rewrite_pass, validate_pass
from pruefstand.perturb.colloquial import Colloquial
from pruefstand.perturb.rewriter import Rewriter
from pruefstand.perturb.validate import RewriteValidator

ITEMS = [
    Item(id="a", text="Wann endet die Kündigungsfrist nach der Probezeit?"),
    Item(id="b", text="Wie viel Urlaub steht Arbeitnehmern zu?"),
    Item(id="c", text="Wer zahlt die Reisekosten bei Dienstreisen?"),
]
OUT = [
    "Wann ist nach der Probezeit Schluss?",
    "Wie viele freie Tage kriege ich?",
    "Wer blecht für Dienstreisen?",
]


def _perturbation(judge_base: str | None = None) -> Colloquial:
    validator = RewriteValidator(client(judge_base, JUDGE), JUDGE) if judge_base else None
    return Colloquial(Rewriter(REWRITER), validator)


async def test_rewrite_pass_stores_every_draft(tmp_path: Path) -> None:
    store = RewriteStore(tmp_path)
    with serve_script(answers(*OUT)) as (rb, rs):
        rep = await rewrite_pass(
            ITEMS, [_perturbation()], llm=client(rb, REWRITER), store=store, seed=0
        )
    assert (rep.done, rep.skipped, rep.remaining, rep.stopped) == (3, 0, 0, None)
    assert rs.posts() == 3
    assert len(RewriteStore(tmp_path).entries()) == 3  # reloaded from disk


async def test_second_run_makes_no_calls(tmp_path: Path) -> None:
    store = RewriteStore(tmp_path)
    with serve_script(answers(*OUT)) as (rb, rs):
        await rewrite_pass(ITEMS, [_perturbation()], llm=client(rb, REWRITER), store=store, seed=0)
        rep = await rewrite_pass(
            ITEMS, [_perturbation()], llm=client(rb, REWRITER), store=RewriteStore(tmp_path), seed=0
        )
    assert (rep.done, rep.skipped) == (0, 3)
    assert rs.posts() == 3


async def test_request_cap_stops_and_the_next_run_resumes(tmp_path: Path) -> None:
    store = RewriteStore(tmp_path)
    with serve_script(answers(*OUT)) as (rb, rs):
        first = await rewrite_pass(
            ITEMS, [_perturbation()], llm=client(rb, REWRITER, max_requests=2), store=store, seed=0
        )
        assert (first.done, first.remaining, first.stopped) == (2, 1, "budget")
        second = await rewrite_pass(
            ITEMS, [_perturbation()], llm=client(rb, REWRITER), store=RewriteStore(tmp_path), seed=0
        )
    assert (second.done, second.skipped, second.remaining, second.stopped) == (1, 2, 0, None)
    assert rs.posts() == 3


async def test_daily_quota_stops_the_pass(tmp_path: Path) -> None:
    quota = Step(429, {"Retry-After": "3600", "x-ratelimit-remaining": "0"})
    with serve_script([*answers(OUT[0]), quota]) as (rb, rs):
        rep = await rewrite_pass(
            ITEMS, [_perturbation()], llm=client(rb, REWRITER), store=RewriteStore(tmp_path), seed=0
        )
    assert (rep.done, rep.remaining, rep.stopped) == (1, 2, "quota")
    assert rs.posts() == 2  # the exhausted model is not called again


async def test_validate_pass_uses_the_stored_drafts_only(tmp_path: Path) -> None:
    store = RewriteStore(tmp_path)
    cache = DictCache()
    with serve_script(answers(*OUT)) as (rb, rs):
        await rewrite_pass(
            ITEMS, [_perturbation()], llm=client(rb, REWRITER, cache=cache), store=store, seed=0
        )
    with serve_script(answers(verdict(1), verdict(0), verdict(1))) as (jb, js):
        outcomes = await validate_pass(ITEMS, [_perturbation(jb)], store=RewriteStore(tmp_path))
    assert rs.posts() == 3  # no further rewrite call
    assert js.posts() == 3
    assert [(o.item_id, o.result.changed) for o in outcomes] == [
        ("a", True),
        ("b", False),
        ("c", True),
    ]
    assert outcomes[1].result.text == ITEMS[1].text


async def test_validate_pass_skips_items_without_a_draft(tmp_path: Path) -> None:
    with serve_script(answers(verdict(1))) as (jb, js):
        outcomes = await validate_pass(ITEMS, [_perturbation(jb)], store=RewriteStore(tmp_path))
    assert outcomes == []
    assert js.posts() == 0


@pytest.mark.parametrize("bad", ["{not json", ""])
def test_corrupt_store_line_is_an_error(tmp_path: Path, bad: str) -> None:
    (tmp_path / "rewrites.jsonl").write_text(bad + "\n" if bad else "\n{x\n", encoding="utf-8")
    with pytest.raises(DatasetError):
        RewriteStore(tmp_path)


async def test_private_items_stay_local(tmp_path: Path) -> None:
    items = [Item(id="a", text=ITEMS[0].text, private=True)]
    with serve_script(answers(OUT[0])) as (rb, rs):
        rep = await rewrite_pass(
            items, [_perturbation()], llm=client(rb, REWRITER), store=RewriteStore(tmp_path), seed=0
        )
    assert rs.posts() == 0
    assert rep.failed == 1


async def test_verdicts_are_stored_so_a_failed_validate_resumes(tmp_path: Path) -> None:
    store = RewriteStore(tmp_path)
    with serve_script(answers(*OUT)) as (rb, _):
        await rewrite_pass(ITEMS, [_perturbation()], llm=client(rb, REWRITER), store=store, seed=0)
    with serve_script([*answers(verdict(1)), Step(500)]) as (jb, _), pytest.raises(LLMError):
        await validate_pass(ITEMS, [_perturbation(jb)], store=RewriteStore(tmp_path))
    with serve_script(answers(verdict(1), verdict(1))) as (jb, js2):
        outcomes = await validate_pass(ITEMS, [_perturbation(jb)], store=RewriteStore(tmp_path))
    assert js2.posts() == 2
    assert [o.result.changed for o in outcomes] == [True, True, True]


def test_item_id_is_a_content_hash() -> None:
    assert item_id("Wann endet die Frist?") == item_id("Wann endet die Frist?")
    assert item_id("Wann endet die Frist?") != item_id("Wann endet die Frist denn?")
    assert item_id("x").startswith("q")

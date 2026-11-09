import re
from pathlib import Path

import pytest
from structlog.testing import capture_logs
from testsupport.judged_support import CAP, chunk, failing, judges, response, user_prompts, verdict
from testsupport.loopback_script import Step, ollama_body
from testsupport.run_builders import make_case

from pruefstand.core.enums import Category
from pruefstand.core.errors import LLMError
from pruefstand.core.models.metric import MetricStatus
from pruefstand.judges.tokens import estimate_tokens
from pruefstand.llm import retry
from pruefstand.metrics.judged.faithfulness import Faithfulness, context_chunks


async def test_a_response_without_chunks_is_not_applicable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with judges(tmp_path, monkeypatch, []) as (pool, state, _):
        value = await Faithfulness().acompute(make_case(0), response(), pool)
    assert (value.status, value.value) == (MetricStatus.NOT_APPLICABLE, None)
    assert value.details["reason"] == "missing_chunks"
    assert user_prompts(state) == []  # no call


async def test_raw_two_is_one_and_the_reason_is_not_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with judges(tmp_path, monkeypatch, [verdict(2)]) as (pool, _, _):
        value = await Faithfulness().acompute(
            make_case(0), response(chunks=(chunk(1, used=True),)), pool
        )
    assert (value.status, value.value) == (MetricStatus.OK, 1.0)
    assert value.details == {"raw_score": 2}  # the judge's reason can echo private text


async def test_all_eight_used_chunks_reach_the_prompt_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chunks = tuple(chunk(i, used=True) for i in range(1, 9))
    with judges(tmp_path, monkeypatch, [verdict(1)]) as (pool, state, _):
        await Faithfulness().acompute(make_case(0), response(chunks=chunks), pool)
    (prompt,) = user_prompts(state)
    assert re.findall(r"\[(\d)\] Absatz", prompt) == [str(n) for n in range(1, 9)]


async def test_only_the_chunks_with_used_in_prompt_true_are_the_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chunks = tuple(chunk(i, used=i in {2, 4, 6, 8}) for i in range(1, 9))
    with judges(tmp_path, monkeypatch, [verdict(1)]) as (pool, state, _):
        await Faithfulness().acompute(make_case(0), response(chunks=chunks), pool)
    (prompt,) = user_prompts(state)
    assert re.findall(r"Absatz (\d):", prompt) == ["2", "4", "6", "8"]


async def test_without_the_flag_the_first_top_k_chunks_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chunks = tuple(chunk(i) for i in range(1, 9))
    with judges(tmp_path, monkeypatch, [verdict(1)]) as (pool, state, _):
        await Faithfulness(top_k=4).acompute(make_case(0), response(chunks=chunks), pool)
    (prompt,) = user_prompts(state)
    assert re.findall(r"Absatz (\d):", prompt) == ["1", "2", "3", "4"]


def test_context_chunks_follow_the_rank_not_the_arrival_order() -> None:
    rows = (chunk(3, used=True), chunk(1, used=True), chunk(2, used=False))
    assert context_chunks(rows, None) == [rows[1].text, rows[0].text]


async def test_an_input_over_the_cap_drops_the_lowest_ranked_chunk_and_logs_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    big = "Die Kündigungsfrist ist geregelt. " * 60  # about 2 KB per chunk
    chunks = tuple(chunk(i, used=True, text=f"Chunk{i} {big}") for i in range(1, 9))
    question = make_case(0).question
    with judges(tmp_path, monkeypatch, [verdict(2)]) as (pool, state, _), capture_logs() as logs:
        value = await Faithfulness().acompute(
            make_case(7), response("Vier Wochen.", chunks=chunks), pool
        )
    (prompt,) = user_prompts(state)
    assert value.status is MetricStatus.OK
    assert value.details["truncated"] is True
    assert "Chunk1 " in prompt
    assert "Chunk8 " not in prompt  # the lowest-ranked chunks go first
    assert question in prompt
    assert "Vier Wochen." in prompt
    sent = state.seen[-1].body["messages"]
    assert isinstance(sent, list)
    assert sum(estimate_tokens(str(m["content"])) for m in sent) <= CAP
    after = value.details["tokens_after"]
    before = value.details["tokens_before"]
    assert isinstance(after, int)
    assert isinstance(before, int)
    assert after <= CAP < before
    (line,) = [x for x in logs if x["event"] == "judge_input_truncated"]
    assert (line["case_id"], line["metric"], line["cap"]) == ("law-0007", "faithfulness", CAP)
    assert (line["tokens_before"], line["tokens_after"]) == (before, after)


async def test_one_huge_chunk_is_cut_at_a_sentence_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = "Satz eins ist kurz. " * 1500
    with judges(tmp_path, monkeypatch, [verdict(2)]) as (pool, state, _):
        value = await Faithfulness().acompute(
            make_case(0), response(chunks=(chunk(1, used=True, text=text),)), pool
        )
    (prompt,) = user_prompts(state)
    assert value.details["truncated"] is True
    assert re.search(r"Satz eins ist kurz\.\n</kontext-[0-9a-f]{8}>", prompt)


async def test_question_and_answer_alone_over_the_cap_are_never_cut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answer = "Antwort. " * 3000
    with judges(tmp_path, monkeypatch, []) as (pool, state, _):
        value = await Faithfulness().acompute(
            make_case(0), response(answer, chunks=(chunk(1, used=True),)), pool
        )
    assert value.status is MetricStatus.NOT_APPLICABLE
    assert value.details["reason"] == "judge_input_too_long"
    assert user_prompts(state) == []


async def test_server_errors_after_all_retries_raise_llm_error_without_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def no_wait(_: float) -> None:
        return None

    monkeypatch.setattr(retry, "pause", no_wait)
    steps = [failing(503)] * 8
    with judges(tmp_path, monkeypatch, steps) as (pool, _, _), pytest.raises(LLMError):
        await Faithfulness().acompute(make_case(0), response(chunks=(chunk(1, used=True),)), pool)


async def test_invalid_judge_output_is_never_echoed_in_the_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "GEHEIM-" + "x" * 8  # stands for canary text a judge could echo back
    steps = [Step(body=ollama_body(secret))] * 2
    with (
        judges(tmp_path, monkeypatch, steps) as (pool, _, _),
        pytest.raises(LLMError) as raised,
    ):
        await Faithfulness().acompute(make_case(0), response(chunks=(chunk(1, used=True),)), pool)
    assert secret not in str(raised.value)
    assert secret not in repr(raised.value)


@pytest.mark.parametrize(
    "category",
    [
        Category.UNANSWERABLE,
        Category.INJECTION,
        Category.LEAK_PROBE,
        Category.FILTER_BYPASS,
        Category.SYSTEM_PROMPT_EXTRACTION,
    ],
)
def test_it_does_not_apply_to_refusal_and_attack_categories(category: Category) -> None:
    applies = Faithfulness().applies_to
    assert applies is not None
    assert category not in applies


async def test_when_no_chunk_reached_the_prompt_it_is_not_applicable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chunks = tuple(chunk(i, used=False) for i in range(1, 4))
    with judges(tmp_path, monkeypatch, []) as (pool, state, _):
        value = await Faithfulness().acompute(make_case(0), response(chunks=chunks), pool)
    assert value.status is MetricStatus.NOT_APPLICABLE
    assert value.details["reason"] == "no_context_used"
    assert user_prompts(state) == []

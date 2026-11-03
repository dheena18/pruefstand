"""The conservative token estimate and the exact cap boundary (X3.9, review M3)."""

from pathlib import Path

import pytest
from testsupport.judged_support import CAP, judges, user_prompts, verdict

from pruefstand.core.errors import LLMError
from pruefstand.core.models.judge import JudgeTask
from pruefstand.judges.output import make_task
from pruefstand.judges.tokens import estimate_tokens


def test_digits_count_one_token_each() -> None:
    assert estimate_tokens("1234567890") == 10
    assert estimate_tokens("ab") == 1


def test_number_dense_text_is_not_undercounted() -> None:
    table = "Az. 12 C 345/21; Betrag 1.234.567,89 EUR; Frist 31.12.2026\n" * 200
    digits = sum(c.isdigit() for c in table)
    assert estimate_tokens(table) >= digits  # the old bytes/3 estimate gave about a third less


async def test_a_prompt_of_exactly_the_cap_is_sent_and_one_token_more_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with judges(tmp_path, monkeypatch, [verdict(1)]) as (pool, state, _):
        judge = pool.for_metric("refusal_judged")

        # the nonce digits differ per input, so walk up to the first length over the cap
        def task(n: int) -> JudgeTask:
            return make_task("refusal_judged", frage="F?", antwort="7" * n)

        n = 1
        while judge.prompt_tokens(task(n)) <= CAP:
            n += 1
        fits, over = task(n - 1), task(n)
        assert judge.prompt_tokens(fits) <= CAP < judge.prompt_tokens(over)
        assert CAP - judge.prompt_tokens(fits) < 12  # within one nonce of the boundary
        await judge.score(fits)
        with pytest.raises(LLMError, match="input cap"):
            await judge.score(over)
    assert len(user_prompts(state)) == 1

"""Calibration against the real gemma3 tokenizer (skipped when the 33 MB file is not installed)."""

import pytest
from testsupport.gpu_files import SHIPPED_CATALOGUE

from pruefstand.judges.exact_tokens import TEMPLATE_TOKENS, load_counter, tokenizer_file
from pruefstand.judges.factory import PROMPT_ROOT
from pruefstand.judges.judge import Judge
from pruefstand.judges.output import SPECS, make_task
from pruefstand.judges.tokens import estimate_tokens
from pruefstand.llm.prompts import PromptRegistry

JUDGE = "ollama/gemma3:12b"
PROSE = (
    "Die Kündigungsfrist für Arbeitnehmer beträgt grundsätzlich vier Wochen zum Fünfzehnten "
    "oder zum Ende eines Kalendermonats, sofern der Vertrag nichts anderes bestimmt. "
)


@pytest.fixture
def counter(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("PRUEFSTAND_GPU_CATALOGUE", str(SHIPPED_CATALOGUE))
    if not tokenizer_file(JUDGE).is_file():
        pytest.skip(
            "the gemma3 tokenizer is not installed (scripts/models/fetch_judge_tokenizer.py)"
        )
    found = load_counter(JUDGE)
    assert found is not None
    return found


def test_the_chat_template_costs_nine_tokens_and_the_calibrated_constant_covers_it(counter) -> None:  # type: ignore[no-untyped-def]
    text = PROSE * 50
    templated = f"<bos><start_of_turn>user\n{text}<end_of_turn>\n<start_of_turn>model\n"
    overhead = counter.count(templated) - counter.count(text)
    assert overhead == 9 <= TEMPLATE_TOKENS == 10  # Ollama measured exactly 10 (D1010)


def test_the_fixed_prefix_of_every_judge_prompt_is_between_500_and_1200_tokens(counter) -> None:  # type: ignore[no-untyped-def]
    judge = Judge.__new__(Judge)
    judge._registry = PromptRegistry([PROMPT_ROOT])
    judge._key = b"k" * 32
    for metric, spec in SPECS.items():
        task = make_task(metric, **dict.fromkeys(spec.variables, "Beispiel."))
        prefix = counter.fixed_prefix(judge._render(task))
        assert 500 <= prefix <= 1_200, (metric, prefix)  # the most a prompt cache can take off


def test_the_estimate_over_counts_german_prose_at_least_twofold(counter) -> None:  # type: ignore[no-untyped-def]
    text = PROSE * 100
    assert estimate_tokens(text) >= 1.8 * counter.count(text)

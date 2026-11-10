"""``prompt_budget`` calibrated on real Ollama numbers (T3.6b, D960).

``fixtures/budget_calibration.json`` was recorded from the real generator
(``gpu/test_record_budget.py``): the ``prompt_eval_count`` Ollama reported for each prompt next to
the local count of the pinned generator tokenizer. The tokenizer file is fetched, not committed
(``make fetch-generator-tokenizer``), so the tests that count with it skip where it is absent.
"""

import json
import os
from pathlib import Path

import pytest
import yaml
from budget_cases import CASES, FIXTURE, case_messages, gpu_config, messages_sha256
from rd_support import MODEL_DIR, REPO

from rag_demo.generation.budget import count_prompt_tokens, is_overflow, prompt_budget
from rag_demo.index.tokens import load_token_counter

CFG = gpu_config()
CATALOGUE_PIN = next(
    m["tokenizer"]["sha256"]
    for m in yaml.safe_load((REPO / "infra" / "gpu" / "models.yaml").read_text(encoding="utf-8"))[
        "models"
    ]
    if m["id"] == CFG.generator.catalogue_id
)
DATA = json.loads(FIXTURE.read_text(encoding="utf-8"))
ROWS = {row["name"]: row for row in DATA["cases"]}
TOKENIZER = Path(os.environ.get("RAG_GENERATOR_TOKENIZER", MODEL_DIR / "tokenizers/generator.json"))
needs_tokenizer = pytest.mark.skipif(
    not TOKENIZER.is_file(), reason="generator tokenizer not fetched"
)
EXACT = ["one_hit", "three_hits", "five_hits", "between_budget_and_num_ctx"]


def test_the_recorded_run_names_its_server_and_pins() -> None:
    assert DATA["ollama_version"] == "0.32.13"
    assert DATA["model"] == "qwen3.8:27b-q8_0"
    assert DATA["num_ctx"] == 8192
    assert DATA["tokenizer"]["sha256"] == CATALOGUE_PIN


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_the_recorded_numbers_belong_to_the_current_prompt(case) -> None:  # type: ignore[no-untyped-def]  # NamedTuple param
    assert ROWS[case.name]["messages_sha256"] == messages_sha256(case_messages(case, CFG)), (
        "prompt or slice changed: re-record with RAG_RECORD=1 (gpu/test_record_budget.py)"
    )


@pytest.mark.parametrize("name", EXACT)
def test_the_wrapper_reproduces_prompt_eval_count_exactly_when_nothing_is_cut(name: str) -> None:
    row = ROWS[name]
    assert row["local_count"] == row["prompt_eval_count"]
    assert is_overflow(row["prompt_eval_count"], row["local_count"], prompt_budget(CFG)) is (
        row["prompt_eval_count"] >= prompt_budget(CFG)
    )


def test_a_prompt_over_num_ctx_is_reported_at_half_the_context_only_the_local_count_sees_it() -> (
    None
):
    row = ROWS["over_num_ctx"]
    assert row["prompt_eval_count"] == 4098  # Ollama cut the prompt to num_ctx / 2 + 2
    assert row["local_count"] > DATA["num_ctx"]
    budget = prompt_budget(CFG)
    assert row["prompt_eval_count"] < budget
    assert is_overflow(row["prompt_eval_count"], None, budget) is False  # no tokenizer: blind
    assert is_overflow(row["prompt_eval_count"], row["local_count"], budget) is True


def test_a_prompt_between_budget_and_num_ctx_is_flagged_by_the_budget_rule_alone() -> None:
    row = ROWS["between_budget_and_num_ctx"]
    budget = prompt_budget(CFG)
    assert budget is not None
    assert budget <= row["prompt_eval_count"] < DATA["num_ctx"]
    assert is_overflow(row["prompt_eval_count"], None, budget) is True


@needs_tokenizer
@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_the_pinned_tokenizer_and_wrapper_give_the_recorded_local_count(case) -> None:  # type: ignore[no-untyped-def]  # NamedTuple param
    count = load_token_counter(TOKENIZER)
    assert (
        count_prompt_tokens(case_messages(case, CFG), count, CFG)
        == (ROWS[case.name]["local_count"])
    )


@needs_tokenizer
def test_the_wrapper_without_the_empty_think_block_would_undercount_by_four_tokens() -> None:
    count = load_token_counter(TOKENIZER)
    messages = case_messages(CASES[0], CFG)
    bare = "".join(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in messages)
    plain = count(bare + "<|im_start|>assistant\n")
    assert ROWS["one_hit"]["prompt_eval_count"] - plain == 4

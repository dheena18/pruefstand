"""Sign (c) of the cut check and the exact judge-token count (T5.2c, D1010)."""

from pathlib import Path

import pytest
import yaml
from testsupport.exact_support import (
    NUM_CTX,
    WINDOW,
    exact_of,
    grow,
    install_tokenizer,
    judge_on,
    long_task,
    make_probe,
)
from testsupport.gpu_files import SHIPPED_CATALOGUE
from testsupport.judge_support import MODEL

from pruefstand.core.errors import ConfigError, JudgeInputTruncated
from pruefstand.judges.exact_tokens import (
    TEMPLATE_TOKENS,
    ExactCounter,
    is_cut,
    load_counter,
    source_url,
)

# --- the counter ----------------------------------------------------------------------------


def test_the_pin_of_the_shipped_judge_is_a_commit_and_the_url_follows_it() -> None:
    entry = yaml.safe_load(SHIPPED_CATALOGUE.read_text(encoding="utf-8"))["models"]
    pin = next(e for e in entry if e["id"] == "ollama/gemma3:12b")["tokenizer"]
    assert "@9478e665381f42974aa06177b019352fb6291876/" in pin["source"]
    assert source_url(pin["source"]).startswith("https://huggingface.co/unsloth/gemma-3-12b-it/")
    assert len(pin["sha256"]) == 64


def test_without_the_file_there_is_no_counter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_tokenizer(tmp_path, monkeypatch, present=False)
    assert load_counter(MODEL) is None
    assert load_counter("github/openai/gpt-4.1-mini") is None


def test_a_file_that_does_not_match_the_pin_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = install_tokenizer(tmp_path, monkeypatch, present=True)
    file.write_bytes(file.read_bytes() + b" ")
    with pytest.raises(ConfigError, match="differs from the catalogue pin"):
        load_counter(MODEL)


def test_the_counter_counts_exactly_and_adds_the_calibrated_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_tokenizer(tmp_path, monkeypatch, present=True)
    counter = load_counter(MODEL)
    assert isinstance(counter, ExactCounter)
    assert counter.count("abc") == 3
    assert TEMPLATE_TOKENS == 10  # 910 - 1.8 x 500 = ... = 10810 - 1.8 x 6000 (D1010)


def test_the_sign_is_a_function_of_window_report_and_cacheable_prefix() -> None:
    assert is_cut(6_147, 14_000, 1_500, 11_904)  # the measured cut
    assert not is_cut(300, 3_000, 1_500, 11_904)  # a short prompt served from cache
    assert not is_cut(11_000, 11_500, 1_500, 11_904)  # honest
    assert not is_cut(
        10_000, 11_500, 1_500, 11_904
    )  # honest, a part of it cached (>= 0.8 x 10 000)
    assert is_cut(7_900, 11_500, 1_500, 11_904)  # well below even a cached report
    assert is_cut(
        1, 11_904, 0, 11_904
    )  # exact >= window: it cannot have fitted, whatever was reported
    assert is_cut(50_000, 12_500, 0, 11_904)


# --- the four branches of Judge._check_not_cut -------------------------------------------------


async def test_a_report_at_the_window_is_a_cut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with (
        judge_on(tmp_path, monkeypatch, WINDOW) as (judge, _),
        pytest.raises(JudgeInputTruncated, match="window leaves"),
    ):
        await judge.score(long_task(40))


async def test_the_measured_signature_is_a_cut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with (
        judge_on(tmp_path, monkeypatch, NUM_CTX // 2 + 3) as (judge, _),
        pytest.raises(JudgeInputTruncated, match="signature of a cut prompt"),
    ):
        await judge.score(long_task(40))


async def test_a_report_far_below_the_exact_count_of_a_prompt_that_fills_the_window_is_a_cut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_tokenizer(tmp_path, monkeypatch, present=True)
    probe, _ = make_probe(tmp_path, monkeypatch)
    chars = 0
    task = long_task(40)
    while True:  # grow the answer until the exact count fills 0.95 of the window
        chars += 100
        task = long_task(chars)
        exact, prefix = exact_of(probe, task)
        if exact >= 0.95 * WINDOW:
            break
    assert probe.prompt_tokens(task) <= probe.input_cap  # the estimate lets it through
    reported = int(0.7 * (exact - prefix))
    assert reported < WINDOW
    assert not NUM_CTX // 2 <= reported <= NUM_CTX // 2 + 16
    with (
        judge_on(tmp_path, monkeypatch, reported) as (judge, _),
        pytest.raises(JudgeInputTruncated, match="the input was cut"),
    ):
        await judge.score(task)


async def test_an_honest_report_and_a_cached_short_prompt_are_not_cuts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_tokenizer(tmp_path, monkeypatch, present=True)
    probe, _ = make_probe(tmp_path, monkeypatch)
    task = long_task(300)
    exact, prefix = exact_of(probe, task)
    assert exact < 0.9 * WINDOW
    for reported in (exact, exact - prefix, 7):  # honest, full prefix cache hit, tiny repeat
        if NUM_CTX // 2 <= reported <= NUM_CTX // 2 + 16:
            continue
        with judge_on(tmp_path / f"r{reported}", monkeypatch, reported) as (judge, _):
            assert (await judge.score(task)).raw_score == 1


async def test_without_the_tokenizer_sign_c_is_skipped_and_the_run_can_say_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    probe_dir = tmp_path / "with"
    probe_dir.mkdir()
    install_tokenizer(probe_dir, monkeypatch, present=True)
    probe, _ = make_probe(probe_dir, monkeypatch)
    task = long_task(2_600)
    exact, prefix = exact_of(probe, task)
    assert exact >= 0.9 * WINDOW
    reported = int(0.7 * (exact - prefix))
    absent = tmp_path / "without"
    absent.mkdir()
    with judge_on(absent, monkeypatch, reported, present=False) as (judge, _):
        assert judge.exact_available is False
        assert (await judge.score(task)).raw_score == 1  # (a) and (b) do not hold, (c) is skipped


async def test_an_exact_count_at_or_above_the_window_is_a_cut_whatever_was_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_tokenizer(tmp_path, monkeypatch, present=True)
    probe, _ = make_probe(tmp_path, monkeypatch)
    task, exact, _ = grow(probe, 1.0)
    assert exact >= WINDOW
    assert probe.prompt_tokens(task) <= probe.input_cap  # the estimate let it through
    reported = 3_000  # honest-looking, outside the band, below the window
    assert not NUM_CTX // 2 <= reported <= NUM_CTX // 2 + 16
    with (
        judge_on(tmp_path, monkeypatch, reported) as (judge, _),
        pytest.raises(JudgeInputTruncated, match="the input was cut"),
    ):
        await judge.score(task)


async def test_a_full_prefix_cache_hit_on_a_prompt_near_the_window_is_not_a_cut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_tokenizer(tmp_path, monkeypatch, present=True)
    probe, _ = make_probe(tmp_path, monkeypatch)
    task, exact, prefix = grow(probe, 0.9)
    assert 0.9 * WINDOW <= exact < WINDOW
    reported = exact - prefix  # the lowest honest report: the whole fixed prefix came from cache
    assert not NUM_CTX // 2 <= reported <= NUM_CTX // 2 + 16
    with judge_on(tmp_path, monkeypatch, reported) as (judge, _):
        assert (await judge.score(task)).raw_score == 1


def test_the_exact_comparison_is_skipped_for_an_answer_of_the_fallback_judge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_tokenizer(tmp_path, monkeypatch, present=True)
    probe, _ = make_probe(tmp_path, monkeypatch)
    task, _, _ = grow(probe, 1.0)
    messages = probe._render(task)
    reported = 3_000
    with pytest.raises(JudgeInputTruncated):
        probe._check_not_cut(reported, messages)
    probe._check_not_cut(reported, messages, fallback=True)

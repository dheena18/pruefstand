"""T3.1b CPU tests: stats, client request building, scoring, redaction, pins (no network)."""

import json
from pathlib import Path

import pytest
import yaml
from model_selection import client, pins, stats
from model_selection.bench_cases import CASES_PATH, load_cases, score_case
from model_selection.vram import parse_status

REPO = Path(__file__).resolve().parents[3]
MODELS = REPO / "infra" / "gpu" / "models.yaml"
CLIENT_SRC = REPO / "experiments" / "model_selection" / "client.py"


def test_json_validity_requires_reason_and_int_score() -> None:
    texts = ['{"reason":"x","score":1}', '{"score":1}', "nonsense"]
    assert stats.validity_rate(texts) == pytest.approx(1 / 3)
    assert not stats.json_valid('{"reason":"x","score":true}')
    assert not stats.json_valid('{"reason":"x","score":"1"}')


def test_throughput_from_timings() -> None:
    assert stats.tok_per_s(100, 2.0) == pytest.approx(50.0)
    assert stats.tok_per_s(100, 0.0) == 0.0


def test_prefill_decode_split_from_ttft() -> None:
    # 3000 prompt tokens, first token at 1.5 s, 100 more by 3.5 s -> prefill 2000, decode 50 tok/s
    prefill, decode = stats.split_prefill_decode(3000, 101, ttft_s=1.5, total_s=3.5)
    assert prefill == pytest.approx(2000.0)
    assert decode == pytest.approx(50.0)


def test_percentile_linear() -> None:
    assert stats.percentile([1.0, 2.0, 3.0, 4.0, 5.0], 50) == pytest.approx(3.0)
    assert stats.percentile([1.0, 2.0], 95) == pytest.approx(1.95)


def test_ndcg_toy() -> None:
    assert stats.ndcg_at_k(["a", "b", "c"], {"a"}, 10) == pytest.approx(1.0)
    assert stats.ndcg_at_k(["x", "y", "a"], {"a"}, 10) == pytest.approx(0.5)
    assert stats.ndcg_at_k(["x", "y"], {"a"}, 10) == 0.0


def test_bootstrap_reproducible_and_decision() -> None:
    scores = [0.0, 1.0, 2.0, 2.0, 1.0, 2.0, 0.0, 2.0]
    assert stats.bootstrap_ci(scores, seed=7) == stats.bootstrap_ci(scores, seed=7)
    mean, lo, hi = stats.bootstrap_ci(scores, seed=7)
    assert lo <= mean <= hi
    a, b = (1.9, 1.8, 2.0), (0.2, 0.1, 0.3)
    assert stats.pick(a, b, cost_a=30.0, cost_b=8.0) == "a"  # CIs apart: the better one wins
    c, d = (1.5, 1.0, 1.9), (1.4, 0.9, 1.8)
    assert stats.pick(c, d, cost_a=30.0, cost_b=8.0) == "b"  # overlap: the cheaper one wins


def test_redact_removes_paths_users_and_ips() -> None:
    text = "see /data/someone/Models and /home/pruefstand/x at 10.1.2.3:2222 user alice"
    out = stats.redact(text, extra={"alice": "<cluster-user>"})
    assert "someone" not in out
    assert "/home/pruefstand" not in out
    assert "10.1.2.3" not in out
    assert "alice" not in out
    assert "<models-dir>" in out
    assert "<home>" in out


def test_parse_status_reads_gpu_lines() -> None:
    csv = (
        "gpu:0,INFO,uuid=GPU-1 used_mib=28135 total_mib=46068\n"
        "gpu:1,INFO,uuid=GPU-2 used_mib=13356 total_mib=46068\n"
        "disk-models,OK,free_kb=4755848 min_free_gb=2\n"
    )
    assert parse_status(csv) == {
        "gpu0_used_mib": 28135,
        "gpu0_total_mib": 46068,
        "gpu1_used_mib": 13356,
        "gpu1_total_mib": 46068,
        "disk_models_free_kb": 4755848,
    }


def test_chat_body_uses_catalogue_options_think_false_and_no_keep_alive() -> None:
    entry = client.load_entry("ollama/gemma3:12b", MODELS)
    body = client.build_chat_body(entry, [{"role": "user", "content": "Hallo"}])
    assert body["model"] == "gemma3:12b"
    assert body["options"] == entry.options
    assert body["options"]["num_ctx"] == 12288
    assert body["think"] is False
    assert body["stream"] is True
    assert "keep_alive" not in body
    with_fmt = client.build_chat_body(entry, [], fmt={"type": "object"})
    assert with_fmt["format"] == {"type": "object"}


def test_client_uses_native_api_only() -> None:
    src = CLIENT_SRC.read_text(encoding="utf-8")
    assert "/v1/" not in src
    assert "keep" + "_alive" not in src
    assert set(client.NATIVE_PATHS.values()) == {
        "/api/chat",
        "/api/embed",
        "/api/ps",
        "/api/show",
        "/api/version",
    }


def test_embed_body_prefix_and_options() -> None:
    entry = client.load_entry("ollama/jeffh/intfloat-multilingual-e5-large-instruct:f16", MODELS)
    body = client.build_embed_body(entry, ["Hallo"], kind="query")
    assert body["input"] == ["query: Hallo"]
    assert body["options"]["num_ctx"] == 512


def test_questions_file_has_at_least_100_items_and_all_kinds() -> None:
    cases = load_cases(CASES_PATH)
    assert len(cases) >= 100
    assert len({c.id for c in cases}) == len(cases)
    kinds = {c.kind for c in cases}
    assert {"law_qa", "summary", "json", "register", "refusal", "umlaut"} <= kinds
    assert all(c.prompt.strip() for c in cases)


def test_score_case_is_deterministic_and_rejects_think_and_english() -> None:
    cases = {c.id: c for c in load_cases(CASES_PATH)}
    reg = next(c for c in cases.values() if c.kind == "register")
    assert (
        score_case(
            reg,
            "Klar, das erkläre ich dir gern. Eine Abmahnung ist eine Rüge, die du bekommst.",
        )
        == 2
    )
    assert score_case(reg, "Gerne erkläre ich Ihnen, was eine Abmahnung ist.") == 0
    assert score_case(reg, "<think>hm</think> Das erkläre ich dir gern.") == 0
    assert score_case(reg, "") == 0


def test_unlocked_catalogue_pin_rules() -> None:
    raw = yaml.safe_load(MODELS.read_text(encoding="utf-8"))
    problems = pins.pin_problems(raw["models"], require_final=False)
    assert problems == []
    final = pins.pin_problems(raw["models"], require_final=True)
    provisional = [m["id"] for m in raw["models"] if m.get("provisional")]
    assert len(final) == len(provisional)
    broken = [{**raw["models"][0], "digest": "abc"}]
    assert pins.pin_problems(broken, require_final=False)


def test_results_csv_has_no_think_in_qwen_answers() -> None:
    for csv in (REPO / "experiments" / "model_selection" / "results").glob("*answers*.jsonl"):
        for line in csv.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if "qwen" in row.get("model", ""):
                assert "<think>" not in row["answer"]


def test_lowercase_ihr_is_not_a_sie_form() -> None:
    reg = next(c for c in load_cases(CASES_PATH) if c.kind == "register")
    assert (
        score_case(reg, "Du bekommst ein Schreiben, und ihr Inhalt ist ernst, das erkläre ich dir.")
        == 2
    )

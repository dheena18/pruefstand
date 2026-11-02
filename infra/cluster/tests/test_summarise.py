"""Tests for the feasibility verdict (T0.6 S3): probe output in, Markdown table and verdict out."""

import pytest
from feasibility.summarise import parse_checks, summarise

GO_IDS = (
    "gpu",
    "ollama",
    "detached-survives-logout",
    "models-space",
    "net",
    "fwd",
    "api-tags",
    "api-chat-nothink",
    "api-ctx",
)


def _probe(**overrides: str) -> str:
    """All go checks PASS; `overrides` maps check id (underscores for dashes) to `STATUS detail`."""
    lines = dict.fromkeys(GO_IDS, "PASS ok")
    lines["logind"] = "PASS Linger=no KillUserProcesses=yes"
    for key, value in overrides.items():
        lines[key.replace("_", "-")] = value
    return "\n".join(f"CHECK {cid} {rest}" for cid, rest in lines.items()) + "\n"


def _verdict(out: str) -> str:
    return out.strip().splitlines()[-1]


def test_all_go_checks_pass_is_go() -> None:
    out = summarise(_probe())
    assert _verdict(out) == "VERDICT: go"
    assert "| gpu | PASS | ok |" in out


def test_model_load_warn_names_first_load_minutes() -> None:
    out = summarise(_probe(model_load="WARN cold load 6 min"))
    assert _verdict(out) == "VERDICT: go-with-conditions"
    assert "first model load ≈ 6 min; excluded from budgets" in out


def test_ollama_list_warn_says_pull_the_generator() -> None:
    out = summarise(_probe(ollama_list="WARN qwen3.8:27b-q8_0 missing"))
    assert _verdict(out) == "VERDICT: go-with-conditions"
    assert "pull it (T3.1a S2b)" in out


@pytest.mark.parametrize(
    "check",
    [
        "models_space",
        "api_chat_nothink",
        "fwd",
        "detached_survives_logout",
        "api_ctx",
        "gpu",
        "ollama",
        "net",
        "api_tags",
    ],
)
def test_fail_of_any_go_check_is_no_go(check: str) -> None:
    out = summarise(_probe(**{check: "FAIL broken"}))
    assert _verdict(out) == "VERDICT: no-go"


def test_models_space_warn_asks_to_free_space() -> None:
    out = summarise(_probe(models_space="WARN 11 GB free"))
    assert _verdict(out) == "VERDICT: go-with-conditions"
    assert "free space on /data first" in out


def test_detached_fail_names_kill_user_processes_value() -> None:
    out = summarise(_probe(detached_survives_logout="FAIL pid 4711 gone after 5 s"))
    assert _verdict(out) == "VERDICT: no-go"
    assert "servers die at SSH logout (KillUserProcesses=yes)" in out


def test_detached_fail_without_logind_check_says_unknown() -> None:
    text = "CHECK detached-survives-logout FAIL gone\n"
    assert "KillUserProcesses=unknown" in summarise(text)


def test_api_ctx_fail_is_no_go() -> None:
    out = summarise(_probe(api_ctx="FAIL prompt_eval_count=2048"))
    assert _verdict(out) == "VERDICT: no-go"
    assert "prompt_eval_count=2048" in out


def test_fwd_fail_port_busy_says_set_probe_port0() -> None:
    out = summarise(_probe(fwd="FAIL local port 21434 in use (set PROBE_PORT0)"))
    assert _verdict(out) == "VERDICT: no-go"
    assert "set PROBE_PORT0" in out.split("Conditions")[1]


@pytest.mark.parametrize("check", ["docker", "vllm", "tmux", "api_openai"])
def test_informational_fail_never_changes_the_verdict(check: str) -> None:
    out = summarise(_probe(**{check: "FAIL absent"}))
    assert _verdict(out) == "VERDICT: go"


def test_informational_warn_never_changes_the_verdict() -> None:
    assert _verdict(summarise(_probe(logind="WARN KillUserProcesses=yes"))) == "VERDICT: go"
    assert _verdict(summarise(_probe(local_disk="WARN full"))) == "VERDICT: go"


def test_port_warn_is_a_condition() -> None:
    out = summarise(_probe(port_11434="WARN held by system ollama.service"))
    assert _verdict(out) == "VERDICT: go-with-conditions"
    assert "stop it or use free ports" in out


def test_ollama_store_warn_points_to_start_script() -> None:
    out = summarise(_probe(ollama_store="WARN model dir ~/.ollama/models"))
    assert _verdict(out) == "VERDICT: go-with-conditions"
    assert "fix ~/start-ollama.sh" in out


def test_gpu_procs_and_provenance_warns_are_conditions() -> None:
    out = summarise(_probe(gpu_procs="WARN pid 7", ollama_provenance="WARN local-only tag"))
    assert _verdict(out) == "VERDICT: go-with-conditions"
    assert "VRAM held by another process" in out
    assert "back up blobs + manifest (T3.1a S2b)" in out


def test_non_go_fail_is_a_condition_not_no_go() -> None:
    out = summarise(_probe(ollama_store="FAIL no server process"))
    assert _verdict(out) == "VERDICT: go-with-conditions"
    assert "ollama-store FAIL" in out


def test_malformed_line_is_ignored_with_a_warning_row() -> None:
    out = summarise("foo\n" + _probe())
    assert _verdict(out) == "VERDICT: go"
    assert "| ? | WARN | ignored line: foo |" in out


def test_unknown_status_is_malformed() -> None:
    checks, bad = parse_checks("CHECK gpu MAYBE x\n")
    assert checks == []
    assert bad == ["CHECK gpu MAYBE x"]


def test_comments_and_blank_lines_are_silent() -> None:
    out = summarise("# probe 2026\n\n" + _probe())
    assert "ignored line" not in out


def test_empty_input_is_no_go() -> None:
    out = summarise("")
    assert _verdict(out) == "VERDICT: no-go"
    assert "no checks" in out


def test_missing_go_check_is_no_go() -> None:
    text = "\n".join(line for line in _probe().splitlines() if " net " not in line)
    out = summarise(text)
    assert _verdict(out) == "VERDICT: no-go"
    assert "net: check missing" in out


def test_last_status_wins_for_duplicate_ids() -> None:
    out = summarise(_probe() + "CHECK gpu FAIL second run\n")
    assert _verdict(out) == "VERDICT: no-go"


def test_pipe_in_detail_is_escaped_in_the_table() -> None:
    out = summarise(_probe(os="PASS a | b"))
    assert "a \\| b" in out


def test_model_load_skip_adds_the_not_measured_condition() -> None:
    out = summarise(_probe(model_load="PASS SKIP: opt-in MEASURE_LOAD=1"))
    assert _verdict(out) == "VERDICT: go-with-conditions"
    assert "cold load not measured" in out


SKIP_LOAD = "CHECK model-load PASS SKIP: opt-in MEASURE_LOAD=1\n"
MEASURED_LOAD = "CHECK model-load PASS cold load 4.5 min (270 s) from <models-dir>\n"


@pytest.mark.parametrize("measured_first", [False, True], ids=["skip-first", "measured-first"])
def test_measured_model_load_beats_skip_in_either_order(measured_first: bool) -> None:
    base = _probe().replace("CHECK model-load", "# x")
    pair = MEASURED_LOAD + SKIP_LOAD if measured_first else SKIP_LOAD + MEASURED_LOAD
    out = summarise(base + pair)
    assert "cold load not measured" not in out
    assert "cold load 4.5 min" in out
    assert "SKIP" not in out
    assert out.count("| model-load |") == 1


def test_stale_skip_condition_goes_but_a_real_warn_stays() -> None:
    text = _probe(models_space="WARN 11 GB free") + SKIP_LOAD + MEASURED_LOAD
    out = summarise(text)
    assert _verdict(out) == "VERDICT: go-with-conditions"
    assert "cold load not measured" not in out
    assert "free space on /data first" in out


def test_skip_alone_still_reports_the_condition() -> None:
    out = summarise(_probe() + SKIP_LOAD)
    assert _verdict(out) == "VERDICT: go-with-conditions"
    assert "cold load not measured" in out


def test_measured_warn_load_after_skip_gives_minutes_condition() -> None:
    out = summarise(_probe() + SKIP_LOAD + "CHECK model-load WARN cold load 6 min\n")
    assert "first model load ≈ 6 min" in out
    assert "cold load not measured" not in out


def test_fail_then_pass_last_result_wins() -> None:
    out = summarise(_probe(gpu="FAIL no gpu") + "CHECK gpu PASS 2 x A40\n")
    assert _verdict(out) == "VERDICT: go"
    assert "no gpu" not in out
    assert out.count("| gpu |") == 1


def test_pass_then_fail_last_result_wins() -> None:
    out = summarise(_probe() + "CHECK gpu FAIL tunnel dropped\n")
    assert _verdict(out) == "VERDICT: no-go"
    assert "gpu FAIL: tunnel dropped" in out
    assert out.count("| gpu |") == 1


def test_table_has_one_row_per_id_in_first_seen_order() -> None:
    text = "CHECK b PASS 1\nCHECK a PASS 1\nCHECK b WARN 2\n"
    rows = [x for x in summarise(text).splitlines() if x.startswith("| ") and "---" not in x][1:]
    assert [r.split(" | ")[0] for r in rows] == ["| b", "| a"]
    assert "| b | WARN | 2 |" in rows

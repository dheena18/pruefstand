"""``scripts/generate_qa.py``: resume, quota stop, cross-check, pass 2, refusals (T4.2 S4, S6).

The datagen answers come from the scripted loopback server (plumbing only; no real model call is
possible from the VM, D604). The real run is an owner/lead [NET] action.
"""

import hashlib
import json
from pathlib import Path

import pytest
from generate_qa import main
from testsupport.loopback_script import Step, serve_script
from testsupport.qa_support import (
    DATAGEN,
    KEY_ENV,
    SECOND,
    client_factory,
    datagen_server,
)

from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.llm.backends.litellm import LiteLLMBackend
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.recorder import CallRecorder

TENANT = "kanzlei_mueller"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_ENV, "-".join(["dummy", "value"]))
    monkeypatch.delenv("PRUEFSTAND_LOCK_HELD", raising=False)


def _argv(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "--tenant",
        TENANT,
        "--n",
        "4",
        "--model",
        DATAGEN,
        "--seed",
        "7",
        "--work-dir",
        str(tmp_path),
        "--run",
        "r",
        *extra,
    ]


def _sha(tmp_path: Path, name: str = "candidates.jsonl") -> str:
    return hashlib.sha256((tmp_path / "r" / name).read_bytes()).hexdigest()


def _lines(tmp_path: Path, name: str = "candidates.jsonl") -> list[dict[str, object]]:
    return [json.loads(x) for x in (tmp_path / "r" / name).read_text("utf-8").splitlines()]


def test_first_run_writes_candidates_and_the_summary_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []
    with datagen_server() as (base, state):
        code = main(_argv(tmp_path), client=client_factory(base, calls))
    assert code == 0
    out = capsys.readouterr().out
    assert "candidates=4 invalid=0 cost_usd=0.00 cross_checked=0 skipped_private=0" in out
    assert len(_lines(tmp_path)) == 4
    assert state.posts() == 4
    summary = json.loads((tmp_path / "r" / "summary.json").read_text("utf-8"))
    assert summary["candidates_sha256"] == _sha(tmp_path)


def test_rerun_gives_identical_candidates_and_sends_no_request(tmp_path: Path) -> None:
    calls: list[str] = []
    with datagen_server() as (base, state):
        main(_argv(tmp_path), client=client_factory(base, calls))
        first, posts = _sha(tmp_path), state.posts()
        assert main(_argv(tmp_path), client=client_factory(base, calls)) == 0
    assert _sha(tmp_path) == first
    assert state.posts() == posts
    assert len(calls) == 1  # the second run never needed a client


def test_request_cap_stops_with_exit_3_and_a_rerun_completes_identically(tmp_path: Path) -> None:
    calls: list[str] = []
    with datagen_server() as (base, state):
        assert (
            main(
                _argv(tmp_path, "--max-requests", "2", "--concurrency", "1"),
                client=client_factory(base, calls),
            )
            == 3
        )
        assert len(_lines(tmp_path)) == 2
        assert state.posts() == 2
        assert main(_argv(tmp_path), client=client_factory(base, calls)) == 0
        assert state.posts() == 4
    resumed = _sha(tmp_path)
    other = tmp_path / "other"
    with datagen_server() as (base, _s):
        main([*_argv(other)[:-2], "--run", "r"], client=client_factory(base, []))
    assert hashlib.sha256((other / "r" / "candidates.jsonl").read_bytes()).hexdigest() == resumed


def test_daily_quota_stops_with_exit_3_and_keeps_the_partial_output(tmp_path: Path) -> None:
    steps = [Step(429, {"Retry-After": "86400"})]
    with datagen_server(steps=steps) as (base, state):
        code = main(_argv(tmp_path, "--concurrency", "1"), client=client_factory(base, []))
    assert code == 3
    assert state.posts() == 1
    assert _lines(tmp_path) == []


def test_cross_check_writes_side_by_side_rows_and_reuses_them(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []
    argv = _argv(tmp_path, "--cross-check", "0.5", "--cross-check-model", SECOND)
    with datagen_server() as (base, state):
        assert main(argv, client=client_factory(base, calls)) == 0
        posts = state.posts()
        rows = _lines(tmp_path, "cross_check.jsonl")
        assert main(argv, client=client_factory(base, calls)) == 0
    assert "cross_checked=2" in capsys.readouterr().out
    assert len(rows) == 2
    assert posts == 6  # 4 primary + 2 second model
    assert state.posts() == posts
    assert calls == [DATAGEN, SECOND]
    assert {r["second_model"] for r in rows} == {SECOND}


def test_excluded_documents_are_not_sampled(tmp_path: Path) -> None:
    exclude = tmp_path / "x.json"
    exclude.write_text(json.dumps({"source_passage_ids": ["gii-arbzg-4", "gii-arbzg-5"]}), "utf-8")
    with datagen_server() as (base, _s):
        main(_argv(tmp_path, "--exclude-file", str(exclude)), client=client_factory(base, []))
    chunk_ids = {str(x["chunk_id"]) for x in _lines(tmp_path)}
    assert not {c for c in chunk_ids if c.startswith(("gii-arbzg-4", "gii-arbzg-5"))}


def test_multi_hop_and_cross_lingual_categories_run(tmp_path: Path) -> None:
    with datagen_server() as (base, _s):
        main(
            [
                "--tenant",
                "shared_public",
                "--n",
                "2",
                "--category",
                "multi_hop",
                "--model",
                DATAGEN,
                "--work-dir",
                str(tmp_path),
                "--run",
                "m",
            ],
            client=client_factory(base, []),
        )
        main(
            [
                "--tenant",
                "stadtwerke_sued",
                "--n",
                "2",
                "--category",
                "cross_lingual",
                "--model",
                DATAGEN,
                "--work-dir",
                str(tmp_path),
                "--run",
                "c",
            ],
            client=client_factory(base, []),
        )
    multi = [
        json.loads(x) for x in (tmp_path / "m" / "candidates.jsonl").read_text("utf-8").splitlines()
    ]
    cross = [
        json.loads(x) for x in (tmp_path / "c" / "candidates.jsonl").read_text("utf-8").splitlines()
    ]
    assert multi
    assert all(r["extra_chunk_ids"] for r in multi + cross)
    assert cross


def test_pass_2_without_judge_makes_no_datagen_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []
    with datagen_server() as (base, _s):
        main(_argv(tmp_path), client=client_factory(base, calls))
        calls.clear()
        assert (
            main(
                _argv(tmp_path, "--pass", "validate", "--no-judge"),
                client=client_factory(base, calls),
            )
            == 0
        )
    assert calls == []
    assert "datagen_calls=0" in capsys.readouterr().out
    assert len(_lines(tmp_path, "validation.jsonl")) == 4


def test_pass_2_with_the_judge_needs_the_gpu_lock(tmp_path: Path) -> None:
    with datagen_server() as (base, _s):
        main(_argv(tmp_path), client=client_factory(base, []))
    assert main(_argv(tmp_path, "--pass", "validate")) == 2


def test_pass_2_without_candidates_is_refused(tmp_path: Path) -> None:
    assert main(_argv(tmp_path, "--pass", "validate", "--no-judge")) == 2


@pytest.mark.parametrize(
    "model", ["github/alibaba/qwen3-32b", "github/google/gemma-3", "ollama/llama3.3:70b"]
)
def test_forbidden_models_are_refused_before_anything_runs(tmp_path: Path, model: str) -> None:
    calls: list[str] = []
    argv = [*_argv(tmp_path)]
    argv[argv.index("--model") + 1] = model
    assert main(argv, client=client_factory("http://127.0.0.1:9", calls)) == 2
    assert calls == []


def test_missing_credential_is_refused_without_printing_anything_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("PRUEFSTAND_GH_MODELS_TOKEN", raising=False)
    assert main(_argv(tmp_path)) == 2
    assert "PRUEFSTAND_GH_MODELS_TOKEN is not set" in capsys.readouterr().err


def test_unsafe_run_name_is_refused(tmp_path: Path) -> None:
    argv = _argv(tmp_path)
    argv[argv.index("--run") + 1] = "../x"
    assert main(argv, client=client_factory("http://127.0.0.1:9", [])) == 2


def test_pass_2_with_the_local_judge_under_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []
    with datagen_server() as (base, state):
        main(_argv(tmp_path), client=client_factory(base, calls))
        datagen_posts = state.posts()
    monkeypatch.setenv("PRUEFSTAND_LOCK_HELD", "1")
    verdict = json.dumps({"supported": True, "reason": "steht im Auszug"}, ensure_ascii=False)
    model = "openai_compatible_local/gemma-test"
    with serve_script(content=verdict) as (judge_base, judge_state):

        def make_judge(ref: ModelRef) -> LLMClient:
            backend = LiteLLMBackend(
                ref.id, api_base=f"{judge_base}/v1", api_key_env=None, timeout_s=30
            )
            policy = LLMPolicyConfig(allowed_providers=("openai_compatible_local",))
            return LLMClient(backend, None, Budget(None, None), CallRecorder(), LLMPolicy(policy))

        argv = _argv(tmp_path, "--pass", "validate", "--judge-model", model)
        assert main(argv, client=client_factory("http://127.0.0.1:9", calls), judge=make_judge) == 0
    rows = _lines(tmp_path, "validation.jsonl")
    assert judge_state.posts() == len(rows) == 4
    assert {r["judge_supported"] for r in rows} == {True}
    assert datagen_posts == 4
    assert "datagen_calls=0" in capsys.readouterr().out

"""Review fixes of #73 for ``scripts/generate_qa.py``: refusals, cross-check stop, cap, ledger."""

import hashlib
import json
from pathlib import Path

import generate_qa_clients
import pytest
from generate_qa import main
from generate_qa_ledger import append_entry, read_ledger
from testsupport.loopback_script import Step
from testsupport.qa_support import (
    DATAGEN,
    KEY_ENV,
    SECOND,
    client_factory,
    datagen_server,
)

from pruefstand.core.errors import StoreError
from pruefstand.core.ids import ChunkId
from pruefstand.core.models.dataset import QACandidate

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


def test_a_mistyped_exclusion_file_is_refused(tmp_path: Path) -> None:
    with datagen_server() as (base, state):
        code = main(
            _argv(tmp_path, "--exclude-file", str(tmp_path / "nope.json")),
            client=client_factory(base, []),
        )
    assert code == 2
    assert state.posts() == 0


def test_an_unreadable_canary_registry_is_refused_not_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(**_: object) -> None:
        msg = "registry is a symlink"
        raise StoreError(msg)

    monkeypatch.setattr(generate_qa_clients, "load_canary_registry", broken)
    monkeypatch.setenv("PRUEFSTAND_GH_MODELS_TOKEN", "-".join(["dummy", "value"]))
    assert main(_argv(tmp_path)) == 2


def test_cross_check_quota_stop_gives_exit_3_and_counts_no_cross_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    steps = [Step(200)] * 4 + [Step(429, {"Retry-After": "86400"})]
    argv = _argv(
        tmp_path, "--cross-check", "0.5", "--cross-check-model", SECOND, "--concurrency", "1"
    )
    with datagen_server(steps=steps) as (base, _s):
        code = main(argv, client=client_factory(base, []))
    assert code == 3
    assert "cross_checked=0" in capsys.readouterr().out


def test_a_same_family_cross_check_model_is_refused_before_any_request(tmp_path: Path) -> None:
    argv = _argv(tmp_path, "--cross-check", "0.5", "--cross-check-model", "github/openai/gpt-4o")
    with datagen_server() as (base, state):
        assert main(argv, client=client_factory(base, [])) == 2
    assert state.posts() == 0


def test_max_requests_is_exact_at_concurrency_4(tmp_path: Path) -> None:
    with datagen_server() as (base, state):
        code = main(_argv(tmp_path, "--max-requests", "2", "--concurrency", "4"),
                    client=client_factory(base, []))  # fmt: skip
    assert code == 3
    assert state.posts() == 2


def test_a_half_written_last_ledger_line_is_cut_off_before_the_next_append(tmp_path: Path) -> None:
    cand = QACandidate(
        question="Q?", answer="A.", citation=None, chunk_id=ChunkId("a#0"), prompt_version="v"
    )
    append_entry(tmp_path, "k1", cand)
    with (tmp_path / "ledger.jsonl").open("a", encoding="utf-8") as f:
        f.write('{"key": "k2", "stat')
    append_entry(tmp_path, "k3", cand)
    assert sorted(read_ledger(tmp_path)) == ["k1", "k3"]
    assert all(json.loads(x) for x in (tmp_path / "ledger.jsonl").read_text().splitlines())

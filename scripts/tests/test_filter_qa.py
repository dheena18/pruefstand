"""``scripts/filter_qa.py`` and its embedding client (T4.3 S4).

The support answers come from the scripted loopback server (plumbing only, D788); the question
vectors are fixed numbers. The real run (support model, BGE-M3) is an owner/lead [GPU]/[NET] action.
"""

import json
from collections.abc import Sequence
from pathlib import Path

import httpx
import numpy as np
import pytest
from filter_qa import main
from filter_qa_embed import Embedder, make_embedder
from generate_qa_args import DEFAULT_CORPUS
from generate_qa_ledger import dump_line
from numpy.typing import NDArray
from testsupport.loopback_script import Step
from testsupport.qa_support import DATAGEN, KEY_ENV, SECOND, client_factory, datagen_server

from pruefstand.core.errors import DatasetError
from pruefstand.core.ids import ChunkId
from pruefstand.core.models.dataset import QACandidate

EVIDENCE = "1. zwei Jahre bestanden hat, einen Monat zum Ende eines Kalendermonats,"
COPY_EVIDENCE = "kann mit einer Frist von vier Wochen zum Fünfzehnten"
ARB_EVIDENCE = "darf acht Stunden nicht überschreiten"
GOOD = "Wie lange vorher muss mir mein Chef kündigen, wenn ich zwei Jahre arbeite?"
COPY = (
    "Mit welcher Frist von vier Wochen zum Fünfzehnten oder zum Ende eines Kalendermonats "
    "kann ich kündigen?"
)
UNRELATED = "Wie viele Stunden darf ich werktäglich höchstens arbeiten?"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_ENV, "-".join(["dummy", "value"]))
    monkeypatch.delenv("PRUEFSTAND_LOCK_HELD", raising=False)


def _embed(_url: str, _api: str, _model: str) -> Embedder:
    def embed(texts: Sequence[str]) -> NDArray[np.float32]:
        return np.array([[1.0, float(i)] for i, _ in enumerate(texts)], dtype=np.float32)

    return embed


def _cand(question: str, chunk_id: str, citation: str, evidence: str | None) -> QACandidate:
    return QACandidate(
        question=question,
        answer="Einen Monat zum Ende eines Kalendermonats.",
        citation=citation,
        chunk_id=ChunkId(chunk_id),
        prompt_version="qa_factual_de_v1",
        evidence_span=evidence,
        style="laie",
    )


def _run_dir(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    run.mkdir()
    rows = [
        _cand(GOOD, "gii-bgb-622#1", "§ 622 Abs. 2 BGB", EVIDENCE),
        _cand(COPY, "gii-bgb-622#0", "§ 622 Abs. 1 BGB", COPY_EVIDENCE),
        _cand(UNRELATED, "gii-arbzg-3#0", "§ 3 ArbZG", ARB_EVIDENCE),
    ]
    (run / "candidates.jsonl").write_text("\n".join(dump_line(r) for r in rows) + "\n", "utf-8")
    return run


def _argv(run: Path, *extra: str) -> list[str]:
    return [
        str(run / "candidates.jsonl"),
        "--corpus-dir", str(DEFAULT_CORPUS),
        "--support-model", SECOND,
        "--generator-model", DATAGEN,
        "--embed-url", "http://embed.invalid",
        *extra,
    ]  # fmt: skip


def test_a_run_writes_the_three_files_and_prints_the_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _run_dir(tmp_path)
    verdict = json.dumps({"reason": "belegt", "score": 1})
    with datagen_server(verdict) as (base, state):
        code = main(_argv(run), client=client_factory(base, []), embedder=_embed)
        assert state.posts() == 2  # the copy never reaches the support model
    out = capsys.readouterr().out
    assert code == 0
    assert "kept=2 unsupported=0 ngram_overlap=1 near_duplicate=0" in out.splitlines()
    report = json.loads((run / "filter_report.json").read_text("utf-8"))
    assert (report["total"], report["kept"], report["reasons"]) == (
        3,
        2,
        {"long_copy": 1, "ngram_overlap": 1},
    )
    kept = (run / "filtered.jsonl").read_text("utf-8").splitlines()
    dropped = [json.loads(x) for x in (run / "filtered_out.jsonl").read_text("utf-8").splitlines()]
    assert len(kept) == 2
    assert dropped[0]["reasons"] == ["ngram_overlap", "long_copy"]
    assert dropped[0]["candidate"]["question"] == COPY


def test_no_support_is_reported_and_makes_no_request(tmp_path: Path) -> None:
    run = _run_dir(tmp_path)
    code = main(_argv(run, "--no-support"), embedder=_embed)
    assert code == 0
    assert json.loads((run / "filter_report.json").read_text("utf-8"))["support"] == "skipped"


def test_a_quota_gives_exit_three_and_keeps_nothing_unchecked_as_kept(tmp_path: Path) -> None:
    run = _run_dir(tmp_path)
    with datagen_server("{}", [Step(429, {"Retry-After": "86400"})]) as (base, _):
        code = main(_argv(run), client=client_factory(base, []), embedder=_embed)
    assert code == 3
    report = json.loads((run / "filter_report.json").read_text("utf-8"))
    assert report["not_checked"] == 2
    assert report["kept"] == 0
    assert not (run / "filtered.jsonl").exists()
    assert (run / "filtered_partial.jsonl").exists()
    assert len((run / "filtered_unjudged.jsonl").read_text("utf-8").splitlines()) == 2


def test_the_family_rule_refuses_with_exit_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _run_dir(tmp_path)
    with datagen_server("{}") as (base, state):
        argv = _argv(run, "--support-model", DATAGEN)
        code = main(argv, client=client_factory(base, []), embedder=_embed)
        assert state.posts() == 0
    assert code == 2
    assert "family" in capsys.readouterr().err
    assert not (run / "filtered.jsonl").exists()


def test_refusals_without_embedding_server_or_lock(tmp_path: Path) -> None:
    run = _run_dir(tmp_path)
    no_embed = [a for a in _argv(run) if a != "http://embed.invalid"]
    no_embed.remove("--embed-url")
    assert main(no_embed, embedder=_embed) == 2
    local = _argv(run, "--support-model", "ollama/gemma3:12b")
    assert main(local, embedder=_embed) == 2


def test_only_a_candidates_file_is_accepted(tmp_path: Path) -> None:
    other = tmp_path / "other.jsonl"
    other.write_text("", "utf-8")
    assert (
        main([str(other), "--embed-url", "http://x.invalid", "--no-support"], embedder=_embed) == 2
    )


def _transport(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


def test_the_tei_embedder_batches_and_returns_float32() -> None:
    sizes: list[int] = []

    def handle(request: httpx.Request) -> httpx.Response:
        inputs = json.loads(request.content)["inputs"]
        sizes.append(len(inputs))
        return httpx.Response(200, json=[[1.0, 0.0]] * len(inputs))

    embed = make_embedder(
        "http://e.invalid/", "tei", "m", client=_transport(httpx.MockTransport(handle))
    )
    got = embed([f"t{i}" for i in range(40)])
    assert sizes == [32, 8]
    assert got.shape == (40, 2)
    assert got.dtype == np.float32


def test_the_ollama_embedder_uses_the_native_endpoint() -> None:
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={"embeddings": [[0.5, 0.5]]})

    embed = make_embedder(
        "http://e.invalid", "ollama", "bge-m3", client=_transport(httpx.MockTransport(handle))
    )
    assert embed(["a"]).shape == (1, 2)
    assert seen == ["/api/embed"]


def test_embedding_failures_are_dataset_errors() -> None:
    bad_shape = httpx.MockTransport(lambda r: httpx.Response(200, json=[[1.0]]))
    down = httpx.MockTransport(lambda r: httpx.Response(503))
    with pytest.raises(DatasetError, match="unexpected shape"):
        make_embedder("http://e.invalid", "tei", "m", client=_transport(bad_shape))(["a", "b"])
    with pytest.raises(DatasetError, match="failed"):
        make_embedder("http://e.invalid", "tei", "m", client=_transport(down))(["a"])


def test_no_support_gets_a_name_that_cannot_be_mistaken_for_a_filtered_set(tmp_path: Path) -> None:
    run = _run_dir(tmp_path)
    assert main(_argv(run, "--no-support"), embedder=_embed) == 0
    assert (run / "filtered_nosupport.jsonl").exists()
    assert not (run / "filtered.jsonl").exists()


def test_summary_json_records_support_and_the_generator_model(tmp_path: Path) -> None:
    run = _run_dir(tmp_path)
    (run / "summary.json").write_text('{"line": "x"}', "utf-8")
    verdict = json.dumps({"reason": None, "score": 1})
    with datagen_server(verdict) as (base, _):
        assert main(_argv(run), client=client_factory(base, []), embedder=_embed) == 0
    entry = json.loads((run / "summary.json").read_text("utf-8"))["filter"]
    assert (entry["support"], entry["generator_model"], entry["complete"]) == (
        "checked",
        DATAGEN,
        True,
    )
    assert entry["support_model"] == SECOND


def test_verdicts_are_logged_and_reused_by_the_next_run(tmp_path: Path) -> None:
    run = _run_dir(tmp_path)
    verdict = json.dumps({"reason": "belegt", "score": 1})
    with datagen_server(verdict) as (base, state):
        assert main(_argv(run), client=client_factory(base, []), embedder=_embed) == 0
        assert state.posts() == 2
    assert len((run / "support_verdicts.jsonl").read_text("utf-8").splitlines()) == 2
    with datagen_server(verdict) as (base, state):
        assert main(_argv(run), client=client_factory(base, []), embedder=_embed) == 0
        assert state.posts() == 0


def test_the_generator_model_comes_from_the_ledger(tmp_path: Path) -> None:
    run = _run_dir(tmp_path)
    key = f"qa_factual_de_v1|{DATAGEN}|gii-bgb-622#1"
    (run / "ledger.jsonl").write_text(
        json.dumps({"key": key, "status": "invalid", "candidate": None}) + "\n", "utf-8"
    )
    argv = [a for a in _argv(run) if a not in {"--generator-model", DATAGEN}]
    verdict = json.dumps({"reason": "belegt", "score": 1})
    with datagen_server(verdict) as (base, _):
        assert main(argv, client=client_factory(base, []), embedder=_embed) == 0
    other = _argv(run, "--generator-model", SECOND)
    assert main(other, embedder=_embed) == 2  # SECOND is not in the ledger


def test_out_of_range_thresholds_are_refused_without_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run = _run_dir(tmp_path)
    assert main(_argv(run, "--no-support", "--max-sim", "1.5"), embedder=_embed) == 2
    err = capsys.readouterr().err
    assert "invalid threshold" in err
    assert "Traceback" not in err


def test_the_embedding_server_is_checked_before_any_support_request(tmp_path: Path) -> None:
    run = _run_dir(tmp_path)

    def down(_u: str, _a: str, _m: str) -> Embedder:
        def embed(_t: Sequence[str]) -> NDArray[np.float32]:
            msg = "embedding request failed (ConnectError)"
            raise DatasetError(msg)

        return embed

    with datagen_server("{}") as (base, state):
        code = main(_argv(run), client=client_factory(base, []), embedder=down)
        assert state.posts() == 0
    assert code == 1

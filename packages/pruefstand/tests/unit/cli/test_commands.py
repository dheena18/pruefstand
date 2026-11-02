"""CLI commands end to end: mini fixture, targets replayed from cassettes of the real rag-demo."""

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from testsupport.pipeline_support import (
    BUG_URL,
    GOOD_URL,
    MINI_CONFIG,
    case_rows,
    config_file,
    mini_config,
    synthetic_config,
    write_dataset,
)
from testsupport.run_builders import make_case
from testsupport.target_cassette import TargetCassette
from typer.testing import CliRunner, Result

from pruefstand.cli import app
from pruefstand.core.config import TargetConfig
from pruefstand.core.enums import GateStatus, Split
from pruefstand.core.models.gate import GateReport, SliceDecision
from pruefstand.store.artifacts import ArtifactStore

MARKER = "<!-- pruefstand:pr-comment -->"


def run_dir(result: Result) -> Path:
    assert result.exit_code == 0, result.output
    return Path(result.stdout.strip().splitlines()[-1])


def do_run(cli: CliRunner, config: Path, out: Path, *extra: str) -> Result:
    return cli.invoke(
        app, ["run", "--config", str(config), "--tier", "pr", "--out", str(out), *extra]
    )


@pytest.fixture
def good_config(tmp_path: Path) -> Path:
    return config_file(tmp_path / "good.yaml", mini_config())


def bug_config(tmp_path: Path, name: str) -> Path:
    target = TargetConfig(type="http", url=BUG_URL, timeout_s=5)
    return config_file(tmp_path / f"{name}.yaml", mini_config(target=target))


def gate(cli: CliRunner, config: Path, candidate: Path, baseline: Path, *extra: str) -> Result:
    args = [
        "gate",
        "--config",
        str(config),
        "--candidate",
        str(candidate),
        "--baseline",
        str(baseline),
    ]
    return cli.invoke(app, [*args, *extra])


# --- validate ---------------------------------------------------------------------------------


def test_validate_the_committed_mini_config(cli: CliRunner) -> None:
    assert cli.invoke(app, ["validate", "config", str(MINI_CONFIG)]).exit_code == 0


def test_validate_a_broken_config_is_exit_two_and_names_the_file(
    cli: CliRunner, tmp_path: Path
) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 1\ntarget: {url: http://x}\nnonsense: true\n", encoding="utf-8")
    result = cli.invoke(app, ["validate", "config", str(bad)])
    assert result.exit_code == 2
    assert "bad.yaml" in result.output


def test_validate_a_dataset(cli: CliRunner, tmp_path: Path) -> None:
    ok = cli.invoke(
        app, ["validate", "dataset", str(MINI_CONFIG.parents[2] / "datasets/fixtures/mini_v0")]
    )
    assert ok.exit_code == 0
    broken = write_dataset(tmp_path, {"smoke": ['{"id": "x"}']})
    bad = cli.invoke(app, ["validate", "dataset", str(broken)])
    assert bad.exit_code == 2
    assert "smoke.jsonl:1" in bad.output


def test_validate_rejects_an_unknown_kind(cli: CliRunner) -> None:
    assert cli.invoke(app, ["validate", "nonsense", "x"]).exit_code == 2


# --- schema -----------------------------------------------------------------------------------


def test_schema_export_writes_the_dataset_manifest_schema(cli: CliRunner, tmp_path: Path) -> None:
    result = cli.invoke(app, ["schema", "export", "--out", str(tmp_path / "s")])
    assert result.exit_code == 0
    assert (tmp_path / "s" / "dataset_manifest.schema.json").is_file()
    assert (tmp_path / "s" / "run_manifest.schema.json").is_file()


# --- run and gate -----------------------------------------------------------------------------


def test_run_replaying_the_good_target(
    cli: CliRunner, good: TargetCassette, good_config: Path, tmp_path: Path
) -> None:
    result = do_run(cli, good_config, tmp_path / "runs")
    directory = run_dir(result)
    assert {p.name for p in directory.iterdir()} >= {
        "run.json",
        "results.parquet",
        "responses.jsonl",
    }
    assert good.misses == []
    manifest = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    assert manifest["dataset_name"] == "mini"
    assert manifest["n_cases"] == 14
    assert manifest["complete"] is True
    assert manifest["splits"] == ["smoke"]
    assert (manifest["stack"], manifest["workload"]) == ("live", "pr")


def test_good_against_good_passes(
    cli: CliRunner, good: TargetCassette, good_config: Path, tmp_path: Path
) -> None:
    one = run_dir(do_run(cli, good_config, tmp_path / "runs"))
    two = run_dir(do_run(cli, good_config, tmp_path / "runs"))
    result = gate(cli, good_config, two, one)
    assert result.exit_code == 0, result.output
    report = GateReport.model_validate_json((two / "gate.json").read_text(encoding="utf-8"))
    assert report.status is GateStatus.PASS
    assert report.hard_fails == ()


def test_the_tenant_bug_is_a_hard_fail(
    cli: CliRunner,
    good: TargetCassette,
    router: respx.MockRouter,
    good_config: Path,
    tmp_path: Path,
) -> None:
    TargetCassette("bug_tenant").install(router, BUG_URL)
    one = run_dir(do_run(cli, good_config, tmp_path / "runs"))
    two = run_dir(do_run(cli, bug_config(tmp_path, "bug"), tmp_path / "runs"))
    result = gate(cli, good_config, two, one)
    assert result.exit_code == 1, result.output
    report = GateReport.model_validate_json((two / "gate.json").read_text(encoding="utf-8"))
    assert report.status is GateStatus.FAIL
    assert "tenant_leak" in {h.metric for h in report.hard_fails}


def _overall(rows: tuple[SliceDecision, ...], metric: str) -> SliceDecision:
    (hit,) = [r for r in rows if (r.metric, r.dimension) == (metric, "overall")]
    return hit


def _nonzero_clusters(base: Path, cand: Path, metric: str) -> int:
    def per_case(path: Path) -> dict[str, tuple[str, float | None]]:
        results = ArtifactStore(path.parent).read_run(path).results
        return {
            str(s.case.id): (
                s.case.cluster_id,
                next(v.value for v in s.values if v.metric == metric),
            )
            for s in results.values
        }

    left, right = per_case(base), per_case(cand)
    diffs: dict[str, float] = {}
    for case_id, (cluster, value) in left.items():
        other = right[case_id][1]
        if value is not None and other is not None:
            diffs[cluster] = diffs.get(cluster, 0.0) + (other - value)
    return sum(1 for d in diffs.values() if abs(d) > 1e-12)


def test_the_citation_bug_is_informational_with_twelve_clusters(  # noqa: PLR0917  (fixtures)
    cli: CliRunner,
    good: TargetCassette,
    router: respx.MockRouter,
    good_config: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    TargetCassette("bug_citations").install(router, BUG_URL)
    monkeypatch.setenv("PRUEFSTAND_STACK", "a40")
    one = run_dir(do_run(cli, good_config, tmp_path / "runs"))
    two = run_dir(do_run(cli, bug_config(tmp_path, "bug"), tmp_path / "runs"))
    result = gate(cli, good_config, two, one)
    assert result.exit_code == 0, result.output
    report = GateReport.model_validate_json((two / "gate.json").read_text(encoding="utf-8"))
    row = _overall((*report.decisions, *report.notable_slices), "citation_recall")
    assert row.gated is False
    assert row.informational_reason == "applicable_clusters<30"
    # decide() reports too few clusters as INSUFFICIENT_DATA even for informational rows (T1.7);
    # the run as a whole stays PASS because informational rows never change it.
    assert row.status is GateStatus.INSUFFICIENT_DATA
    assert report.status is GateStatus.PASS
    assert row.result is not None
    assert row.result.mean_diff < 0
    wanted = "sign_test" if _nonzero_clusters(one, two, "citation_recall") < 10 else "bootstrap"
    assert row.result.method == wanted


def test_tier_one_marks_the_same_pair_as_deterministic_only(
    cli: CliRunner,
    good: TargetCassette,
    router: respx.MockRouter,
    good_config: Path,
    tmp_path: Path,
) -> None:
    TargetCassette("bug_citations").install(router, BUG_URL)
    one = run_dir(do_run(cli, good_config, tmp_path / "runs"))
    two = run_dir(do_run(cli, bug_config(tmp_path, "bug"), tmp_path / "runs"))
    assert gate(cli, good_config, two, one).exit_code == 0
    report = GateReport.model_validate_json((two / "gate.json").read_text(encoding="utf-8"))
    row = _overall((*report.decisions, *report.notable_slices), "citation_recall")
    assert row.informational_reason == "tier1_deterministic_only"


def test_a_corpus_mismatch_is_exit_one_and_no_query_is_sent(
    cli: CliRunner, router: respx.MockRouter, good_config: Path, tmp_path: Path
) -> None:
    other = TargetCassette("good", info_overrides={"corpus_version": "other-v9"})
    other.install(router, GOOD_URL)
    result = do_run(cli, good_config, tmp_path / "runs")
    assert result.exit_code == 1
    assert "other-v9" in result.output
    assert other.query_requests == 0
    (directory,) = (tmp_path / "runs").iterdir()
    manifest = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    assert manifest["stop_reason"] == "aborted"
    assert manifest["counts"]["corpus_mismatch"] == 1


def test_ingest_is_not_implemented_yet(cli: CliRunner) -> None:
    result = cli.invoke(app, ["ingest", "--config", "corpus.yaml", "--out", "corpus/"])
    assert result.exit_code == 2
    assert "T2.5" in result.output


# --- report -----------------------------------------------------------------------------------


@pytest.fixture
def gated_pair(cli: CliRunner, good: TargetCassette, good_config: Path, tmp_path: Path) -> Path:
    one = run_dir(do_run(cli, good_config, tmp_path / "runs"))
    two = run_dir(do_run(cli, good_config, tmp_path / "runs"))
    assert gate(cli, good_config, two, one).exit_code == 0
    return two


def test_report_markdown_starts_with_marker_and_verdict(cli: CliRunner, gated_pair: Path) -> None:
    result = cli.invoke(app, ["report", "--run", str(gated_pair), "--format", "md"])
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == MARKER
    assert lines[1].startswith("## Prüfstand")  # tier 1 reads "## Prüfstand tier 1: ✅ PASS ..."
    assert "✅ PASS" in lines[1]


def test_report_json_is_the_gate_report(cli: CliRunner, gated_pair: Path) -> None:
    result = cli.invoke(app, ["report", "--run", str(gated_pair), "--format", "json"])
    assert result.exit_code == 0
    assert GateReport.model_validate_json(result.stdout).status is GateStatus.PASS


@pytest.mark.parametrize("fmt", ["html", "evidence"])
def test_report_html_and_evidence_wait_for_t6_4(cli: CliRunner, gated_pair: Path, fmt: str) -> None:
    result = cli.invoke(app, ["report", "--run", str(gated_pair), "--format", fmt])
    assert result.exit_code == 2
    assert "T6.4" in result.output


def test_report_without_gate_json_is_a_usage_error(cli: CliRunner, gated_pair: Path) -> None:
    (gated_pair / "gate.json").unlink()
    result = cli.invoke(app, ["report", "--run", str(gated_pair), "--format", "md"])
    assert result.exit_code == 2
    assert "gate" in result.output


def test_publish_without_token_or_repository_is_a_config_error(
    cli: CliRunner, gated_pair: Path
) -> None:
    result = cli.invoke(
        app, ["report", "--run", str(gated_pair), "--format", "md", "--publish-pr", "7"]
    )
    assert result.exit_code == 2
    assert "GITHUB_TOKEN" in result.output


def test_publish_posts_the_comment_without_printing_the_token(
    cli: CliRunner, gated_pair: Path, router: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = "synthetic-" + "x" * 12
    monkeypatch.setenv("GITHUB_TOKEN", token)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    router.get("https://api.github.com/user").mock(return_value=httpx.Response(403))
    router.get("https://api.github.com/repos/owner/repo/issues/7/comments").mock(
        return_value=httpx.Response(200, json=[])
    )
    post = router.post("https://api.github.com/repos/owner/repo/issues/7/comments").mock(
        return_value=httpx.Response(201, json={"id": 5})
    )
    result = cli.invoke(
        app, ["report", "--run", str(gated_pair), "--format", "md", "--publish-pr", "7"]
    )
    assert result.exit_code == 0, result.output
    assert post.called
    assert MARKER in json.loads(post.calls[0].request.content)["body"]
    assert token not in result.output
    assert post.calls[0].request.headers["authorization"] == f"Bearer {token}"


# --- blocks, strata, splits (R12 N1.2, R13 P4.3 / P4.4) ----------------------------------------


@pytest.fixture
def full_config(tmp_path: Path, router: respx.MockRouter) -> Path:
    base = "http://target.test"
    router.get(f"{base}/v1/info").respond(404)
    router.post(f"{base}/v1/query").respond(
        200, json={"answer": "Antwort", "citations": [], "chunks": [], "refused": False}
    )
    rows = []
    for block in range(3):
        rows += case_rows([make_case(10 * block + j, split="full", block=block) for j in range(2)])
    rows += case_rows(
        [
            make_case(
                100 + j,
                split="full",
                category="unanswerable",
                expect_refusal=True,
                gold_doc_ids=[],
                gold_citations=[],
                reference_answer=None,
            )
            for j in range(2)
        ]
    )
    core = case_rows([make_case(200 + j, split="core") for j in range(2)])
    smoke = case_rows([make_case(300 + j, split="smoke") for j in range(2)])
    dataset = write_dataset(tmp_path / "ds", {"full": rows, "core": core, "smoke": smoke})
    return config_file(tmp_path / "full.yaml", synthetic_config(dataset, (Split.FULL,)))


def manifest_of(result: Result) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((run_dir(result) / "run.json").read_text(encoding="utf-8"))
    return data


def test_block_flag_is_written_to_run_json(
    cli: CliRunner, full_config: Path, tmp_path: Path
) -> None:
    result = do_run(cli, full_config, tmp_path / "r", "--split", "full", "--block", "2")
    manifest = manifest_of(result)
    assert manifest["block"] == 2
    assert manifest["n_cases"] == 4  # block 2 + two refusal cases


@pytest.mark.parametrize(
    ("counter", "expected"),
    [("4", 1), ("5", 2), ("3", 0), ("7", 1)],
)
def test_block_auto_reads_the_counter_file(  # noqa: PLR0917  (parametrized fixtures)
    cli: CliRunner,
    full_config: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    counter: str,
    expected: int,
) -> None:
    state = tmp_path / "home" / "state"
    state.mkdir(parents=True)
    (state / "nightly_counter").write_text(counter + "\n", encoding="utf-8")
    manifest = manifest_of(
        do_run(cli, full_config, tmp_path / "r", "--split", "full", "--block", "auto")
    )
    assert manifest["block"] == expected


def test_the_counter_variable_names_the_file_and_wins(
    cli: CliRunner, full_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "home" / "state"
    state.mkdir(parents=True)
    (state / "nightly_counter").write_text("4", encoding="utf-8")
    other = tmp_path / "elsewhere" / "c"
    other.parent.mkdir()
    other.write_text("7", encoding="utf-8")
    monkeypatch.setenv("PRUEFSTAND_NIGHTLY_COUNTER", str(other))
    manifest = manifest_of(
        do_run(cli, full_config, tmp_path / "r", "--split", "full", "--block", "auto")
    )
    assert manifest["block"] == 1
    other.write_text("5", encoding="utf-8")
    assert (
        manifest_of(
            do_run(cli, full_config, tmp_path / "r2", "--split", "full", "--block", "auto")
        )["block"]
        == 2
    )


def test_a_missing_counter_file_is_block_zero(
    cli: CliRunner, full_config: Path, tmp_path: Path
) -> None:
    manifest = manifest_of(
        do_run(cli, full_config, tmp_path / "r", "--split", "full", "--block", "auto")
    )
    assert manifest["block"] == 0


@pytest.mark.parametrize("content", ["abc", "-1", "", "1.5", "99999999999999999999999999"])
def test_an_unparsable_counter_is_exit_two(
    cli: CliRunner, full_config: Path, tmp_path: Path, content: str
) -> None:
    state = tmp_path / "home" / "state"
    state.mkdir(parents=True)
    (state / "nightly_counter").write_text(content, encoding="utf-8")
    result = do_run(cli, full_config, tmp_path / "r", "--split", "full", "--block", "auto")
    assert result.exit_code == 2
    assert "nightly_counter" in result.output


def test_block_auto_does_not_depend_on_the_clock(
    cli: CliRunner, full_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "home" / "state"
    state.mkdir(parents=True)
    (state / "nightly_counter").write_text("4", encoding="utf-8")
    blocks = []
    for index, stamp in enumerate(("2026-12-31T22:00:00+00:00", "2027-01-01T00:30:00+00:00")):
        frozen = time.mktime(time.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S"))
        monkeypatch.setattr(time, "time", lambda frozen=frozen: frozen)
        blocks.append(
            manifest_of(
                do_run(
                    cli, full_config, tmp_path / f"r{index}", "--split", "full", "--block", "auto"
                )
            )["block"]
        )
    assert blocks == [1, 1]


def test_stratum_refusal_is_recorded(cli: CliRunner, full_config: Path, tmp_path: Path) -> None:
    manifest = manifest_of(
        do_run(cli, full_config, tmp_path / "r", "--split", "full", "--stratum", "refusal")
    )
    assert manifest["stratum"] == "refusal"
    assert manifest["n_cases"] == 2


@pytest.mark.parametrize(
    "extra",
    [
        ["--split", "full", "--stratum", "refusal", "--block", "1"],
        ["--split", "core", "--block", "1"],
        ["--split", "core", "--stratum", "blocks"],
        ["--split", "full", "--split", "core", "--block", "1"],
        ["--split", "smoke", "--judged-subset"],
        ["--split", "full", "--block", "7"],
        ["--split", "full", "--block", "sometimes"],
        ["--split", "nonsense"],
        ["--split", "rq1"],
    ],
)
def test_invalid_selection_flags_are_exit_two(
    cli: CliRunner, full_config: Path, tmp_path: Path, extra: list[str]
) -> None:
    assert do_run(cli, full_config, tmp_path / "r", *extra).exit_code == 2


def test_split_flags_override_the_configured_splits(
    cli: CliRunner, full_config: Path, tmp_path: Path
) -> None:
    manifest = manifest_of(
        do_run(cli, full_config, tmp_path / "r", "--split", "smoke", "--split", "core")
    )
    assert manifest["splits"] == ["smoke", "core"] or set(manifest["splits"]) == {"smoke", "core"}
    assert manifest["n_cases"] == 4


def test_the_config_hash_sees_the_effective_splits(
    cli: CliRunner, full_config: Path, tmp_path: Path
) -> None:
    default = manifest_of(do_run(cli, full_config, tmp_path / "a"))
    overridden = manifest_of(do_run(cli, full_config, tmp_path / "b", "--split", "core"))
    assert default["config_hash"] != overridden["config_hash"]


def test_a_counter_that_is_a_fifo_is_exit_two_and_does_not_hang(
    cli: CliRunner, full_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fifo = tmp_path / "counter"
    os.mkfifo(fifo)
    monkeypatch.setenv("PRUEFSTAND_NIGHTLY_COUNTER", str(fifo))
    result = do_run(cli, full_config, tmp_path / "r", "--split", "full", "--block", "auto")
    assert result.exit_code == 2
    assert "nightly counter" in result.output


def test_a_counter_that_is_a_directory_is_exit_two(
    cli: CliRunner, full_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PRUEFSTAND_NIGHTLY_COUNTER", str(tmp_path))
    result = do_run(cli, full_config, tmp_path / "r", "--split", "full", "--block", "auto")
    assert result.exit_code == 2

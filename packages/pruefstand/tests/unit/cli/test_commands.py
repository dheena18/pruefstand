"""CLI commands end to end: mini fixture, targets replayed from cassettes of the real rag-demo."""

import json
from pathlib import Path

import httpx
import pytest
import respx
from testsupport.cli_support import do_run, gate, run_dir
from testsupport.pipeline_support import (
    BUG_URL,
    GOOD_URL,
    MINI_CONFIG,
    config_file,
    mini_config,
    write_dataset,
)
from testsupport.target_cassette import TargetCassette
from typer.testing import CliRunner

from pruefstand.cli import app
from pruefstand.core.config import TargetConfig
from pruefstand.core.enums import GateStatus
from pruefstand.core.models.gate import GateReport, SliceDecision
from pruefstand.store.artifacts import ArtifactStore

MARKER = "<!-- pruefstand:pr-comment -->"


def bug_config(tmp_path: Path, name: str) -> Path:
    target = TargetConfig(type="http", url=BUG_URL, timeout_s=5)
    return config_file(tmp_path / f"{name}.yaml", mini_config(target=target))


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


def test_ingest_with_a_missing_config_is_a_usage_error(cli: CliRunner, tmp_path: Path) -> None:
    result = cli.invoke(
        app, ["ingest", "--config", str(tmp_path / "corpus.yaml"), "--out", str(tmp_path / "o")]
    )
    assert result.exit_code == 2
    assert "corpus.yaml" in result.output


# --- report -----------------------------------------------------------------------------------


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

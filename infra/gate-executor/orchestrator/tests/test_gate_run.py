"""gate_run (D1095): digest from the image status, candidate env, config rewrite, argv, outcome."""

import json
from collections.abc import Mapping
from pathlib import Path

import pytest
import yaml
from gate_orchestrator.candidate import ALLOWED_ENV
from gate_orchestrator.gate_run import (
    candidate_env,
    digest_from_status,
    gate_argv,
    ip_argv,
    pruefstand_run_argv,
    read_outcome,
    run_config,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
DIGEST = "sha256:" + "b" * 64


@pytest.mark.parametrize(
    ("status", "digest"),
    [
        ({"state": "success", "description": f"signed {DIGEST}"}, DIGEST),
        (
            {"state": "success", "description": "signed", "target_url": f"https://x/{DIGEST}"},
            DIGEST,
        ),
        ({"state": "pending", "description": DIGEST}, None),
        ({"state": "success", "description": "sha256:short"}, None),
        (None, None),
    ],
)
def test_digest_from_status(status: dict[str, str] | None, digest: str | None) -> None:
    assert digest_from_status(status) == digest


def test_candidate_env_is_inside_the_sandbox_allow_list() -> None:
    env = candidate_env({"QDRANT_API_KEY": "k", "PUBLIC_TOKEN": "t", "DASHBOARD_DATA_PAT": "p"})
    assert set(env) <= ALLOWED_ENV
    assert env["QDRANT_API_KEY"] == "k"
    assert env["RAG_CONFIG"] == "/app/configs/rag.gpu.yaml"
    assert "PRUEFSTAND_CANDIDATE_API_KEY" not in candidate_env({})


def test_run_config_rewrites_only_the_target_url(tmp_path: Path) -> None:
    main = REPO_ROOT / "pruefstand.yaml"
    out = run_config(main, tmp_path / "pruefstand.yaml", "http://10.231.5.7:8000")
    before, after = (
        yaml.safe_load(main.read_text(encoding="utf-8")),
        yaml.safe_load(out.read_text("utf-8")),
    )
    assert after["target"]["url"] == "http://10.231.5.7:8000"
    after["target"]["url"] = before["target"]["url"]
    assert after == before


def test_argv_builders() -> None:
    assert ip_argv("c1")[-1] == "c1"
    run = pruefstand_run_argv(Path("c.yaml"), Path("runs"), judged_subset=True)
    assert run == [
        "pruefstand",
        "run",
        "--config",
        "c.yaml",
        "--tier",
        "pr",
        "--out",
        "runs",
        "--judged-subset",
    ]
    assert "--judged-subset" not in pruefstand_run_argv(Path("c"), Path("r"), judged_subset=False)
    assert gate_argv(Path("runs/r1"), Path("c.yaml"))[-4:] == [
        "--ref",
        "main",
        "--config",
        "c.yaml",
    ]


def _run_dir(tmp: Path, gate: Mapping[str, object], infra: str | None = None) -> Path:
    run = tmp / "r1"
    run.mkdir()
    (run / "gate.json").write_text(json.dumps(gate), encoding="utf-8")
    (run / "run.json").write_text(
        json.dumps({"run_id": "r1", "infra_error": infra}), encoding="utf-8"
    )
    return run


def test_outcome_of_a_finished_gate(tmp_path: Path) -> None:
    gate = {
        "status": "FAIL",
        "candidate_run_id": "r1",
        "eval_fingerprint": "fp",
        "no_baseline": False,
    }
    outcome = read_outcome(_run_dir(tmp_path, gate))
    assert (outcome.status, outcome.summary, outcome.no_baseline, outcome.infra_error) == (
        "FAIL",
        "r1",
        False,
        None,
    )


def test_outcome_without_baseline_names_the_fingerprint(tmp_path: Path) -> None:
    gate = {
        "status": "INSUFFICIENT_DATA",
        "candidate_run_id": "r1",
        "eval_fingerprint": "fp",
        "no_baseline": True,
    }
    assert read_outcome(_run_dir(tmp_path, gate)).summary == "fp"


def test_outcome_carries_the_runs_infra_error(tmp_path: Path) -> None:
    gate = {"status": "INSUFFICIENT_DATA", "candidate_run_id": "r1"}
    assert read_outcome(_run_dir(tmp_path, gate, "ollama_down: x")).infra_error == "ollama_down: x"


def test_gate_json_without_status_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no status"):
        read_outcome(_run_dir(tmp_path, {"candidate_run_id": "r1"}))

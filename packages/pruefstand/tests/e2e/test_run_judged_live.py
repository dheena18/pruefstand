"""The four judged metrics inside a real tier-1 ``pruefstand run`` (T5.2b).

Needs the `live` stack (`make e2e-live`), a GitHub Models token (``PRUEFSTAND_GH_MODELS_TOKEN``,
Models: read) and ``PRUEFSTAND_NONCE_KEY``; GitHub Models is not reachable from the VM, so the CI
tier-1 job or the owner runs it. Assertions are on statuses and counts, never on scores.
"""

import json
import os
from pathlib import Path

import polars as pl
import pytest
from testsupport.e2e_support import DATASET, ROOT, call, run_dir

pytestmark = [pytest.mark.e2e, pytest.mark.live]

JUDGED = ["faithfulness", "answer_correctness", "perturbation_consistency", "refusal_judged"]
# read at import: the e2e conftest removes the token from the environment of every test
_TOKEN = os.environ.get("PRUEFSTAND_GH_MODELS_TOKEN")
_NONCE = os.environ.get("PRUEFSTAND_NONCE_KEY")


@pytest.fixture(autouse=True)
def _judged_env(monkeypatch: pytest.MonkeyPatch) -> None:
    if not _TOKEN or not _NONCE:
        pytest.skip("needs PRUEFSTAND_GH_MODELS_TOKEN and PRUEFSTAND_NONCE_KEY (GitHub Models)")
    monkeypatch.delenv("PRUEFSTAND_JUDGE_MODE", raising=False)  # tier 1 live: github when a token
    monkeypatch.setenv("PRUEFSTAND_GH_MODELS_TOKEN", _TOKEN)
    monkeypatch.setenv("PRUEFSTAND_NONCE_KEY", _NONCE)


def test_the_judged_metrics_run_on_at_most_ten_cases(target_url: str, tmp_path: Path) -> None:
    text = (ROOT / "examples" / "live" / "pruefstand.yaml").read_text(encoding="utf-8")
    text = text.replace("http://localhost:8000", target_url)
    text = text.replace("datasets/fixtures/slice_v1", str(DATASET))
    config = tmp_path / "judged.yaml"
    config.write_text(text, encoding="utf-8")
    done = call("run", "--config", str(config), "--tier", "pr", "--out", str(tmp_path / "runs"))
    directory = run_dir(done)
    table = pl.read_parquet(directory / "results.parquet")
    rows = table.filter(pl.col("metric").is_in(JUDGED))
    assert set(rows["metric"].unique()) == set(JUDGED)
    assert set(rows["status"].unique()) <= {"ok", "not_applicable"}
    manifest = json.loads((directory / "run.json").read_text(encoding="utf-8"))
    assert manifest["judged_cases"] <= 10
    assert manifest["judge_mode"] in {"github", "skipped"}
    gated = call(
        "gate", "--config", str(config), "--candidate", str(directory), "--baseline", str(directory)
    )
    assert gated.exit_code == 0, gated.output
    gate = json.loads((directory / "gate.json").read_text(encoding="utf-8"))
    reasons = {
        row["metric"]: row["informational_reason"]
        for row in gate["notable_slices"]
        if row["metric"] in JUDGED
    }
    assert set(reasons.values()) <= {"tier1_judged"}

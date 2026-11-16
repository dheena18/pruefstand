"""T5.4d: one fresh real run of the A40 judge on its majority anchors is not drift (D1250).

Runs on the VM under the GPU lock (``pruefstand-lock uv run pytest -m "live and gpu" <this file>``);
the unit twin on recorded answers is ``unit/pipeline/test_judge_drift.py``.
"""

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.judges.anchors import anchor_file, load_anchors
from pruefstand.judges.status import drift_threshold_of
from pruefstand.llm.factory import build_backend
from pruefstand.pipeline.judge_drift import run_judge_drift

JUDGE = "ollama/gemma3:12b"

pytestmark = [
    pytest.mark.live,
    pytest.mark.gpu,
    pytest.mark.skipif(
        not os.environ.get("OLLAMA_GPU1_URL") or not anchor_file(JUDGE).is_file(),
        reason="needs OLLAMA_GPU1_URL (VM tunnel) and the anchor file",
    ),
]


def test_a_fresh_run_on_the_majority_anchors_is_not_drift(tmp_path: Path) -> None:
    assert {a.majority_runs for a in load_anchors(anchor_file(JUDGE))} == {5}
    threshold = drift_threshold_of(JUDGE)
    assert threshold is not None
    backend = build_backend(ModelRef(id=JUDGE, family="gemma"), policy=LLMPolicyConfig())
    result = run_judge_drift(
        JUDGE, anchor_file(JUDGE), backend, tmp_path, threshold=threshold, now=datetime.now(UTC)
    )
    assert result.n == 50
    assert result.status == "ok", f"{result.changed} of 50 changed (threshold {threshold})"

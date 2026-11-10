"""Records the real A40 judge's answers to the 50 drift anchors for
``unit/pipeline/test_judge_drift.py``.

Run by ``record_cassettes.sh --judge-drift`` on the VM under the GPU lock, after
``experiments/rq2/anchors.py`` wrote the anchor file. Skipped without
``PRUEFSTAND_RECORD_JUDGE_DRIFT=1``.
"""

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.judges.anchors import anchor_file
from pruefstand.llm.cassettes import CassetteRecorder
from pruefstand.llm.factory import build_backend
from pruefstand.pipeline.judge_drift import run_judge_drift

CASSETTES = Path(__file__).resolve().parents[2] / "cassettes" / "judge_drift"
JUDGE = "ollama/gemma3:12b"

pytestmark = [
    pytest.mark.live,
    pytest.mark.gpu,
    pytest.mark.skipif(
        os.environ.get("PRUEFSTAND_RECORD_JUDGE_DRIFT") != "1",
        reason="set PRUEFSTAND_RECORD_JUDGE_DRIFT=1 (record_cassettes.sh --judge-drift)",
    ),
]


def test_record_the_anchor_answers(tmp_path: Path) -> None:
    real = build_backend(ModelRef(id=JUDGE, family="gemma"), policy=LLMPolicyConfig())
    backend = CassetteRecorder(CASSETTES, "record").wrap(real)
    result = run_judge_drift(JUDGE, anchor_file(JUDGE), backend, tmp_path, now=datetime.now(UTC))
    assert result.n == 50
    assert len(list(CASSETTES.glob("*.json"))) == 50

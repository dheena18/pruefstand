"""Runner against the real rag-demo (tier-1 live job after T1.13).

Runs only when ``PRUEFSTAND_TARGET_URL`` is set and ``datasets/fixtures/slice_v1/core.jsonl``
exists; skipped with a reason otherwise.
"""

import os
from pathlib import Path

import pytest
from testsupport.runner_support import make_runner, run_cases, values_of

from pruefstand.adapters.http import HttpTargetAdapter
from pruefstand.core.config import HttpTargetConfig
from pruefstand.core.models.testcase import TestCase

pytestmark = pytest.mark.live

SLICE = Path(__file__).resolve().parents[5] / "datasets" / "fixtures" / "slice_v1" / "core.jsonl"
URL = os.environ.get("PRUEFSTAND_TARGET_URL")


@pytest.mark.skipif(URL is None, reason="PRUEFSTAND_TARGET_URL is not set (no live target)")
@pytest.mark.skipif(not SLICE.exists(), reason="datasets/fixtures/slice_v1 does not exist yet")
async def test_ten_slice_cases_against_the_real_rag_demo() -> None:
    assert URL is not None
    lines = SLICE.read_text(encoding="utf-8").splitlines()[:10]
    cases = [TestCase.model_validate_json(line) for line in lines]
    adapter = HttpTargetAdapter(HttpTargetConfig(type="http", url=URL, timeout_s=60))
    try:
        results = await run_cases(make_runner(adapter, concurrency=2, timeout_s=60), cases)
    finally:
        await adapter.aclose()
    assert len(results.records) == 10
    for i in range(10):
        values = values_of(results, i)
        assert values["error_rate"].value == 0.0
        latency = values["latency_ms"].value
        assert latency is not None
        assert latency > 0

"""T5.4 S10: the nightly drift step on recorded real anchor answers (cassettes, D253/D308)."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pruefstand.core.models.llm import LLMRequest, LLMResponse
from pruefstand.judges.anchors import AnchorItem, anchor_file, load_anchors
from pruefstand.judges.output import output_model
from pruefstand.llm.cache_epochs import current_epoch, read_drift
from pruefstand.llm.cassettes import CassetteRecorder
from pruefstand.llm.client import cache_key
from pruefstand.pipeline.fingerprints import calibration_epoch
from pruefstand.pipeline.judge_drift import DriftResult, run_judge_drift

JUDGE = "ollama/gemma3:12b"
CASSETTES = Path(__file__).resolve().parents[2] / "cassettes" / "judge_drift"
NOW = datetime(2026, 11, 10, 3, 0, tzinfo=UTC)

needs_cassettes = pytest.mark.skipif(
    not anchor_file(JUDGE).is_file() or len(list(CASSETTES.glob("*.json"))) < 50,
    reason="no anchor file / drift cassettes yet: record_cassettes.sh --judge-drift",
)


class Spy:
    """Counts the backend calls of the replayed real answers."""

    def __init__(self) -> None:
        self.inner = CassetteRecorder(CASSETTES, "replay").wrap(None)
        self.calls = 0

    async def acomplete(self, req: LLMRequest) -> LLMResponse:
        self.calls += 1
        return await self.inner.acomplete(req)


def _recorded_scores(anchors: list[AnchorItem]) -> list[int]:
    spy = Spy()

    async def one(a: AnchorItem) -> int:
        resp = await spy.acomplete(a.request())
        return output_model(a.metric).model_validate_json(resp.text).score

    return [asyncio.run(one(a)) for a in anchors]


def _other(metric: str, score: int) -> int:
    """A raw score that differs from ``score`` on the metric's scale."""
    if metric in {"refusal_judged", "perturbation_consistency"}:
        return 1 - score
    return 0 if score else 2


def _anchors_with(tmp_path: Path, disagree: int) -> Path:
    anchors = load_anchors(anchor_file(JUDGE))
    fresh = _recorded_scores(anchors)
    rows = []
    for k, (anchor, score) in enumerate(zip(anchors, fresh, strict=True)):
        stored = score if k >= disagree else _other(anchor.metric, score)
        rows.append(anchor.model_copy(update={"raw_score": stored}).model_dump_json())
    path = tmp_path / "anchors.jsonl"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def _run(path: Path, cache: Path, spy: Spy | None = None) -> DriftResult:
    backend = spy or Spy()
    return run_judge_drift(JUDGE, path, backend, cache, a0=1.0, now=NOW)


@needs_cassettes
def test_all_agree_writes_no_flag_and_keeps_the_epoch(tmp_path: Path) -> None:
    spy = Spy()
    result = _run(_anchors_with(tmp_path, 0), tmp_path / "cache", spy)
    assert result.status == "ok"
    assert spy.calls == 50  # sent with the cache bypassed: no client cache exists here
    assert read_drift(tmp_path / "cache") is None
    assert current_epoch(tmp_path / "cache", JUDGE) == 0


@needs_cassettes
def test_four_changed_anchors_are_not_drift(tmp_path: Path) -> None:
    result = _run(_anchors_with(tmp_path, 4), tmp_path / "cache")
    assert result.status == "ok"
    assert result.changed == 4


@needs_cassettes
def test_five_changed_anchors_flag_drift_and_invalidate_the_cache(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    req = load_anchors(anchor_file(JUDGE))[0].request()
    before_key = cache_key(req, None, current_epoch(cache, JUDGE))
    epoch_before = calibration_epoch()
    result = _run(_anchors_with(tmp_path, 5), cache)
    assert result.status == "drift"
    flag = read_drift(cache)
    assert flag is not None
    assert (flag.changed, flag.threshold, flag.a0) == (5, 5, 1.0)
    assert json.loads((cache / "judge_drift.json").read_text(encoding="utf-8"))["model"] == JUDGE
    assert (
        cache_key(req, None, current_epoch(cache, JUDGE)) != before_key
    )  # a cached verdict misses
    assert calibration_epoch() == epoch_before  # judge_epoch (and eval_fingerprint) unchanged


def test_a_missing_anchor_file_is_skipped(tmp_path: Path) -> None:
    result = _run(tmp_path / "missing.jsonl", tmp_path / "cache")
    assert result.status == "skipped"

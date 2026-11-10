"""The nightly judge drift step (T5.4 S10; interfaces §6/§15, D114, D253, D308).

Re-judges the stored anchors of one judge **with the cache bypassed** (the client is built here
without a cache), compares the raw scores (``anchor_agreement``) and applies ``is_drift`` with the
judge's calibrated threshold. On drift it bumps the judge's cache epoch (``invalidate_judge``) and
writes ``judge_drift.json``; later runs then mark that judge's metrics informational
(``judge_drift``). Drift never changes ``eval_fingerprint`` or ``judge_epoch``. A local judge whose
re-run passes clears its earlier flag (``clear_drift``); a hosted judge keeps it until a
re-calibration passes.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from pruefstand.core.config import LLMPolicyConfig
from pruefstand.core.logging import get_logger
from pruefstand.core.models.judge import JudgeVerdict
from pruefstand.core.protocols import LLMBackend
from pruefstand.judges.anchors import AnchorItem, load_anchors, verdict_of
from pruefstand.judges.drift import anchor_agreement, default_threshold, is_drift
from pruefstand.judges.output import output_model
from pruefstand.llm.budget import Budget
from pruefstand.llm.cache_epochs import DRIFT_FILE, DriftFlag, clear_drift, invalidate_judge
from pruefstand.llm.client import LLMClient
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.recorder import CallRecorder

_log = get_logger(__name__)
CONCURRENCY = 4  # production OLLAMA_NUM_PARALLEL


@dataclass(frozen=True)
class DriftResult:
    """Outcome of one drift check (``skipped`` when there is no anchor file)."""

    status: Literal["ok", "drift", "skipped"]
    n: int = 0
    agreement: float | None = None
    changed: int | None = None
    threshold: int | None = None


async def _fresh(client: LLMClient, anchors: list[AnchorItem]) -> list[JudgeVerdict]:
    gate = asyncio.Semaphore(CONCURRENCY)

    async def one(anchor: AnchorItem) -> JudgeVerdict:
        async with gate:
            out, _ = await client.complete_json_meta(anchor.request(), output_model(anchor.metric))
        return verdict_of(anchor.metric, out.score, anchor.judge_model)

    return list(await asyncio.gather(*(one(a) for a in anchors)))


def _write_flag(cache_dir: Path, flag: DriftFlag) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / DRIFT_FILE).write_text(flag.model_dump_json(), encoding="utf-8")


def run_judge_drift(
    model: str,
    anchors_path: Path,
    backend: LLMBackend,
    cache_dir: Path,
    *,
    threshold: int | None = None,
    a0: float | None = None,
    now: datetime,
) -> DriftResult:
    """Re-judge the anchors of ``model`` and flag drift.

    Args:
        model: The judge's model id (must match the anchors' ``judge_model``).
        anchors_path: The judge's anchor file.
        backend: The real judge backend; wrapped in an ``LLMClient`` without a cache.
        cache_dir: Directory of ``cache_epochs.json`` and ``judge_drift.json``.
        threshold: The judge's calibrated threshold (None: the N3 default).
        a0: The judge's self-agreement (recorded only).
        now: Timestamp written to the flag.

    Returns:
        The result; ``skipped`` without an anchor file (logged, not an error).

    Raises:
        ConfigError: The anchor file is invalid or belongs to another judge.
        LLMError: A judge call failed after the retries.

    Must not be called from a running event loop (it runs its own).
    """
    if not anchors_path.is_file():
        _log.info(
            "judge_drift_skipped", model=model, reason="no anchor file", path=str(anchors_path)
        )
        return DriftResult("skipped")
    anchors = load_anchors(anchors_path)
    _check_owner(model, anchors)
    policy = LLMPolicyConfig()
    client = LLMClient(backend, None, Budget(None, None), CallRecorder(), LLMPolicy(policy))
    fresh = asyncio.run(_fresh(client, anchors))
    n = len(anchors)
    agreement = anchor_agreement([a.stored_verdict() for a in anchors], fresh)
    changed = n - round(agreement * n)
    used = default_threshold(n) if threshold is None else threshold
    if not is_drift(agreement, n, a0=a0, threshold=threshold):
        if model.startswith("ollama/"):
            clear_drift(cache_dir, model)
        _log.info(
            "judge_drift_ok", model=model, agreement=agreement, changed=changed, threshold=used
        )
        return DriftResult("ok", n, agreement, changed, used)
    epoch = invalidate_judge(cache_dir, model)
    flag = DriftFlag(
        model=model,
        agreement=agreement,
        epoch=epoch,
        ts=now.isoformat(),
        changed=changed,
        threshold=used,
        a0=a0,
    )
    _write_flag(cache_dir, flag)
    _log.warning("judge_drift", model=model, agreement=agreement, changed=changed, threshold=used)
    return DriftResult("drift", n, agreement, changed, used)


def _check_owner(model: str, anchors: list[AnchorItem]) -> None:
    from pruefstand.core.errors import ConfigError  # noqa: PLC0415 - only on the error path

    others = sorted({a.judge_model for a in anchors} - {model})
    if others or not anchors:
        msg = f"anchor file is not {model}'s ({others or 'empty'})"
        raise ConfigError(msg)

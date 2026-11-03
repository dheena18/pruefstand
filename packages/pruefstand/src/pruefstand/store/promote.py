"""What may become a baseline, and the block-k projection of the release run (R13 D321, N1.4).

``prepare_promotion`` is the single entry of ``pruefstand baseline promote``; the stores call
``check_promotable`` and ``check_ref_block`` again in ``put`` so no caller can bypass them.
"""

import re
from collections import Counter

from pruefstand.core.config.gate import JUDGED_METRICS
from pruefstand.core.errors import ConfigError, StoreError
from pruefstand.core.fingerprint import eval_fingerprint
from pruefstand.core.models.metric import MetricStatus
from pruefstand.core.models.run import RunArtifacts, RunManifest, RunResults, ScoredCase
from pruefstand.core.models.target import CaseRecord
from pruefstand.store.baseline_index import REFS

JUDGE_TRUNCATED_SHARE = 0.05
"""More truncated judge inputs than this share of the judged cases block a promotion (the gate's
``_TRUNCATED_SHARE``; a test keeps both equal, because ``store`` cannot import ``pipeline``)."""
_BLOCK_REF = re.compile(r"(nightly|release)-b([0-2])")


class BaselineRefused(StoreError):  # noqa: N818  (reads as a verdict, like BudgetExceeded)
    """The run may not become a baseline (incomplete, or flagged); the store is unchanged."""


def flagged_reason(manifest: RunManifest) -> str | None:
    """Why ``manifest`` must never become a baseline, or None (D224, D226, AI13-08).

    Args:
        manifest: The run.

    Returns:
        A sentence for the user, or None for a promotable run.
    """
    if not manifest.complete:
        detail = f", infra_error={manifest.infra_error}" if manifest.infra_error else ""
        return (
            f"run {manifest.run_id} is not complete (stop_reason={manifest.stop_reason}{detail}); "
            "only complete runs become baselines"
        )
    if manifest.judge_fallback:
        judges = ", ".join(sorted(set(manifest.judge_models.values()))) or "unknown"
        return (
            f"judge fallback run ({judges}): not promoted; "
            "judged metrics are never compared across judges"
        )
    if manifest.stack != "live" and manifest.judge_mode == "skipped":
        return (
            f"run {manifest.run_id} ran without judges (judge_mode=skipped) in tier 2: not promoted"
        )
    for flag in ("judge_drift", "judge_degraded"):
        if getattr(manifest, flag):
            return f"run {manifest.run_id} has {flag}=true: flagged runs are never promoted"
    truncated = manifest.counts.get("judge_truncated", 0)
    if manifest.judged_cases > 0 and truncated > JUDGE_TRUNCATED_SHARE * manifest.judged_cases:
        return (
            f"run {manifest.run_id}: more than {JUDGE_TRUNCATED_SHARE:.0%} of the judged cases "
            "were truncated (judge_truncated): not promoted"
        )
    return None


def check_promotable(manifest: RunManifest) -> None:
    """Refuse an incomplete or flagged run.

    Raises:
        BaselineRefused: ``flagged_reason`` is not None.
    """
    reason = flagged_reason(manifest)
    if reason is not None:
        raise BaselineRefused(reason)


def check_ref_block(manifest: RunManifest, ref: str) -> None:
    """Check that a run is stored under a ref that matches its block (N1.4).

    Raises:
        StoreError: ``main`` with a block, or ``nightly-b<k>`` / ``release-b<k>`` without block k.
    """
    match = _BLOCK_REF.fullmatch(ref)
    if match is None:
        if manifest.block is not None:
            msg = f"ref {ref} takes runs without a block; this run has block {manifest.block}"
            raise StoreError(msg)
        return
    if manifest.block != int(match.group(2)):
        msg = f"ref {ref} needs a run with block {match.group(2)}, not {manifest.block}"
        raise StoreError(msg)


def prepare_promotion(run: RunArtifacts, ref: str) -> RunArtifacts:
    """Validate a promotion and return the run to store.

    ``main`` takes a run without a block; ``nightly-b<k>`` a run with ``block == k``;
    ``release-b<k>`` the release run (``block is None``, ``stratum == "all"``), stored as its
    block-k projection (refusal stratum plus block k, fingerprint recomputed, D321).

    Args:
        run: The run read from its run directory.
        ref: The target ref.

    Returns:
        ``run`` itself, or the projection for a ``release-b<k>`` ref.

    Raises:
        ConfigError: Unknown ref, or the run does not fit the ref (usage error, exit 2).
        BaselineRefused: The run is incomplete or flagged (exit 1).
        StoreError: The release run cannot be projected (mixed corpus versions).
    """
    manifest = run.results.manifest
    if ref not in REFS:
        msg = f"unknown ref {ref!r}; use one of {', '.join(REFS)}"
        raise ConfigError(msg)
    match = _BLOCK_REF.fullmatch(ref)
    kind = match.group(1) if match else "main"
    if kind == "main" and manifest.block is not None:
        msg = f"ref main takes runs without a block; this run has block {manifest.block}"
        raise ConfigError(msg)
    if kind == "nightly" and match and manifest.block != int(match.group(2)):
        msg = f"ref {ref} needs a run with block {match.group(2)}, not {manifest.block}"
        raise ConfigError(msg)
    if kind == "release" and (manifest.block is not None or manifest.stratum != "all"):
        msg = (
            f"ref {ref} needs the release run of all of full (block None, stratum 'all'); "
            f"this run has block={manifest.block}, stratum={manifest.stratum!r}"
        )
        raise ConfigError(msg)
    check_promotable(manifest)
    if kind == "release" and match:
        return project_release(run, int(match.group(2)))
    return run


def project_release(run: RunArtifacts, block: int) -> RunArtifacts:
    """Cut the block-``block`` projection out of the release run (R13 D321).

    Keeps the refusal stratum (cases without a block) and the cases of ``block``, sets
    ``RunManifest.block`` and recomputes ``eval_fingerprint`` with ``core.fingerprint`` (never by
    hand), so it equals the fingerprint of the nightly of that block. Per-case counters are
    recounted; run-level counters (``model_reloads``, judge errors, ...) cannot be split and are
    dropped; ``cost`` and ``duration_s`` stay those of the release run.

    Args:
        run: The release run.
        block: 0, 1 or 2.

    Returns:
        The projection (same ``run_id`` and root).

    Raises:
        StoreError: The kept cases come from more than one corpus version.
    """
    results = run.results
    kept = tuple(s for s in results.values if s.case.block in (None, block))
    ids = {s.case.id for s in kept}
    records = tuple(r for r in results.records if r.case_id in ids)
    corpora = {s.case.corpus_version for s in kept}
    if len(corpora) != 1:
        msg = f"cannot project the release run: its cases name {len(corpora)} corpus versions"
        raise StoreError(msg)
    counts, judged = _recount(records, kept)
    manifest = _projected_manifest(results.manifest, block, next(iter(corpora)))
    manifest = manifest.model_copy(
        update={"n_cases": len(kept), "counts": counts, "judged_cases": judged}
    )
    projected = RunResults(manifest=manifest, records=records, values=kept)
    return RunArtifacts(results=projected, root=run.root)


def _projected_manifest(old: RunManifest, block: int, corpus_version: str) -> RunManifest:
    """``old`` with ``block`` set and ``eval_fingerprint`` recomputed by ``core.fingerprint``."""
    fingerprint = eval_fingerprint(
        dataset_name=old.dataset_name,
        dataset_version=old.dataset_version,
        splits=old.splits,
        judge_models=old.judge_models,
        judge_prompt_versions=old.judge_prompt_versions,
        judge_serving=old.judge_serving,
        judge_epoch=old.judge_epoch,
        metric_versions=old.metric_versions,
        corpus_version=corpus_version,
        block=block,
        judged_subset=old.judged_subset,
        stratum="all",
    )
    return old.model_copy(
        update={
            "block": block,
            "stratum": "all",
            "eval_fingerprint": fingerprint,
            "artifact_sha256": {},
        }
    )


def _recount(
    records: tuple[CaseRecord, ...], kept: tuple[ScoredCase, ...]
) -> tuple[dict[str, int], int]:
    """Recount the per-case counters of the runner for the kept cases."""
    counts: Counter[str] = Counter()
    judged = 0
    for record in records:
        counts["error" if record.error is not None else "ok"] += 1
        counts["cached"] += record.cached
        counts["retrieve"] += record.mode == "retrieve"
    for scored in kept:
        attempted = False
        for value in scored.values:
            counts["not_applicable"] += value.status is MetricStatus.NOT_APPLICABLE
            is_judged = value.metric in JUDGED_METRICS
            attempted = attempted or (is_judged and value.status is not MetricStatus.NOT_APPLICABLE)
            if value.details.get("truncated") is True:
                counts["judge_truncated" if is_judged else "metric_truncated"] += 1
            mismatch = value.details.get("refusal_flag_mismatch")
            if isinstance(mismatch, int | float):
                counts["refusal_flag_mismatch"] += int(mismatch)
        judged += attempted
    return {k: v for k, v in counts.items() if v}, judged

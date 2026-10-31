"""The only place fingerprints are computed (interfaces §17, D36). Pure: no I/O, no clock."""

import re
from collections.abc import Mapping, Sequence
from typing import Literal

from pruefstand.core.enums import Split
from pruefstand.core.hashing import stable_hash
from pruefstand.core.models.corpus import CorpusManifest
from pruefstand.core.models.target import TargetInfo

_DATE_TAG = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def corpus_version(manifest: CorpusManifest, date_tag: str) -> str:
    """Return ``"<date_tag>.<sha8>"`` for a corpus manifest.

    The hash covers ``sources``, ``tenants`` and ``sha256`` (sorted by key). The manifest's own
    ``corpus_version`` and ``created_at`` are excluded, so the result has no circularity and
    needs no clock.

    Args:
        manifest: The corpus manifest.
        date_tag: Build date as ``YYYY-MM-DD``.

    Returns:
        E.g. ``"2026-11-02.ab12cd34"``.

    Raises:
        ValueError: ``date_tag`` is not ``YYYY-MM-DD``.
    """
    if not _DATE_TAG.fullmatch(date_tag):
        msg = f"date_tag must match YYYY-MM-DD, got {date_tag!r}"
        raise ValueError(msg)
    digest = stable_hash(
        sorted(manifest.sources.items()),
        sorted(manifest.tenants.items()),
        sorted(manifest.sha256.items()),
    )
    return f"{date_tag}.{digest[:8]}"


def target_fingerprint(info: TargetInfo | None, *, url: str, run_id: str) -> str:
    """Fingerprint of the system under test (target cache key).

    Covers ``image_digest`` (else ``git_sha``), ``config_hash``, ``corpus_version``, ``models`` and
    the static ``serving`` fields. Runtime counters never enter it. An opaque target
    (``info is None``) is keyed on ``(url, run_id)``, so its cache is never reused across runs.

    Args:
        info: The target's ``/v1/info``, or None for an opaque target.
        url: The target's base URL (opaque targets only).
        run_id: The current run id (opaque targets only).

    Returns:
        16 hex characters.
    """
    if info is None:
        return stable_hash(url, run_id)
    return stable_hash(
        info.image_digest or info.git_sha,
        info.config_hash,
        info.corpus_version,
        sorted(info.models.items()),
        sorted(info.serving.items()),
    )


def eval_fingerprint(  # noqa: PLR0913  (signature fixed by interfaces §2; coding-standards §1.1)
    *,
    dataset_name: str,
    dataset_version: str,
    splits: Sequence[Split],
    judge_models: Mapping[str, str],
    judge_prompt_versions: Mapping[str, str],
    judge_serving: Mapping[str, str],
    judge_epoch: int,
    metric_versions: Mapping[str, str],
    corpus_version: str,
    block: int | None = None,
    judged_subset: bool = False,
    stratum: Literal["all", "refusal", "blocks"] = "all",
) -> str:
    """Fingerprint of what a run measures; a gate compares only runs with an equal value.

    ``judge_models``, ``judge_prompt_versions`` and ``judge_serving`` are the configured judges
    whose metrics are **gated** in the run (empty in tier 1); run-time flags (drift, degraded,
    fallback, quota) are not parameters. ``block`` and ``judged_subset`` always enter the hash;
    ``stratum`` enters it only when it is not ``"all"``, so fingerprints computed before
    ``stratum`` existed stay unchanged (R13 D322).

    Args:
        dataset_name: Dataset name.
        dataset_version: Dataset version.
        splits: Splits run (order irrelevant).
        judge_models: Metric to gated judge model id.
        judge_prompt_versions: Metric to judge prompt version.
        judge_serving: Metric to ``"<engine> <version> <quantization> <digest[:12]>"``.
        judge_epoch: Calibration epoch.
        metric_versions: Metric name to version.
        corpus_version: See ``corpus_version``.
        block: Nightly block 0, 1 or 2; None for no block filter.
        judged_subset: True if judged metrics ran on the judged subset only.
        stratum: Case selector inside ``full``.

    Returns:
        16 hex characters.
    """
    parts: list[object] = [
        dataset_name,
        dataset_version,
        sorted(split.value for split in splits),
        sorted(judge_models.items()),
        sorted(judge_prompt_versions.items()),
        sorted(judge_serving.items()),
        judge_epoch,
        sorted(metric_versions.items()),
        corpus_version,
        block,
        judged_subset,
    ]
    if stratum != "all":
        parts.append(stratum)
    return stable_hash(*parts)

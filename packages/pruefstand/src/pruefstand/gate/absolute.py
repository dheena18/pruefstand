"""Absolute checks (T1.7 step 7): ``max_value`` metrics decided by the Wilson lower bound.

Gated on the ``overall`` slice only (unperturbed cases): k events among n candidate cases with a
value (for ``error_rate``: all candidate cases). The same rate on each ``tenant``/``lang`` value
is reported with ``gated=False`` and ``notable = k/n > max_value`` (per-slice counts of a 1 % event
would warn on almost every no-op PR). Values must be 0 or 1.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from pruefstand.core.config import GatePolicy
from pruefstand.core.enums import GateStatus
from pruefstand.core.models.gate import SliceDecision
from pruefstand.core.models.metric import MetricStatus
from pruefstand.core.models.run import RunResults, ScoredCase
from pruefstand.gate._validate import fail
from pruefstand.gate.decision import decide_absolute

_SLICE_DIMENSIONS = ("tenant", "lang")


@dataclass
class _Tally:
    k: int = 0
    n: int = 0
    clusters: set[str] = field(default_factory=set)


def _groups(case_tenant: str, case_lang: str, dims: Iterable[str]) -> list[tuple[str, str]]:
    groups = [("overall", "overall")]
    if "tenant" in dims:
        groups.append(("tenant", case_tenant))
    if "lang" in dims:
        groups.append(("lang", case_lang))
    return groups


def _event(scored: ScoredCase, metric: str) -> int | None:
    """Return 1/0 for an ``ok`` value, ``None`` if the case has none; fail on a non-binary value."""
    value = next((v for v in scored.values if v.metric == metric), None)
    if value is None or value.status is not MetricStatus.OK or value.value is None:
        return None
    if value.value not in (0.0, 1.0):
        fail(f"{metric}: absolute-check values must be 0 or 1, got {value.value!r}")
    return int(value.value == 1.0)


def _tally(
    run: RunResults, metric: str, dims: Iterable[str], *, all_cases: bool
) -> dict[tuple[str, str], _Tally]:
    out: dict[tuple[str, str], _Tally] = {}
    for scored in run.values:
        case = scored.case
        if case.perturbation is not None:
            continue
        hit = _event(scored, metric)
        if hit is None and not all_cases:
            continue
        for key in _groups(str(case.tenant), case.lang.value, dims):
            tally = out.setdefault(key, _Tally())
            tally.k += hit or 0
            tally.n += 1
            tally.clusters.add(case.cluster_id)
    return out


def _row(
    metric: str,
    key: tuple[str, str],
    tally: _Tally,
    *,
    base_rate: float,
    max_value: float,
    reason: str | None,
    paired_overall: GateStatus | None,
) -> SliceDecision:
    rate = tally.k / tally.n
    gated = key == ("overall", "overall") and reason is None
    status = GateStatus.PASS
    if gated:
        status = decide_absolute(tally.k, tally.n, max_value=max_value)
        if paired_overall is GateStatus.WARN and status is GateStatus.PASS:
            status = GateStatus.WARN  # SPEC §7.2: "or the paired max_drop rule warns"
    return SliceDecision(
        metric=metric,
        dimension=key[0],
        value=key[1],
        status=status,
        gated=gated,
        notable=not gated and rate > max_value,
        baseline_mean=base_rate,
        candidate_mean=rate,
        result=None,
        p_adjusted=None,
        mde=None,
        max_value=max_value,
        n_clusters=len(tally.clusters),
        informational_reason=reason,
    )


def absolute_checks(
    baseline: RunResults,
    candidate: RunResults,
    policy: GatePolicy,
    informational: Mapping[str, str],
    paired_overall: Mapping[str, GateStatus],
) -> tuple[SliceDecision, ...]:
    """Return the absolute-check rows: gated ``overall`` rows first, then by metric/dimension/value.

    Args:
        baseline: Baseline run (only for the displayed baseline rate).
        candidate: Candidate run.
        policy: Gate policy; every metric with ``max_value`` is checked.
        informational: metric -> reason; such a metric's rows are ``gated=False`` and ``PASS``.
        paired_overall: metric -> status of its gated paired ``overall`` decision; a ``WARN``
            there raises the absolute row to at least ``WARN``.

    Returns:
        The rows (rows with no case are omitted).

    Raises:
        GateInputError: A value of an absolute-check metric is neither 0 nor 1.
    """
    dims = tuple(d for d in _SLICE_DIMENSIONS if d in policy.slices)
    rows: list[SliceDecision] = []
    for metric in sorted(policy.metrics):
        limit = policy.metrics[metric].max_value
        if limit is None:
            continue
        everyone = metric == "error_rate"
        cand = _tally(candidate, metric, dims, all_cases=everyone)
        base = _tally(baseline, metric, dims, all_cases=everyone)
        for key, tally in cand.items():
            earlier = base.get(key)
            base_rate = earlier.k / earlier.n if earlier and earlier.n else 0.0
            rows.append(
                _row(
                    metric,
                    key,
                    tally,
                    base_rate=base_rate,
                    max_value=limit,
                    reason=informational.get(metric),
                    paired_overall=paired_overall.get(metric),
                )
            )
    rows.sort(key=lambda r: (not r.gated, r.metric, r.dimension != "overall", r.dimension, r.value))
    return tuple(rows)

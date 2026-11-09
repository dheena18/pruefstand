"""Pairing of two runs for one metric (T1.7 step 3 and 4): ``ScoreTable``, ``PairedTable``, slices.

``score_table`` turns one run into the values of one metric; ``pair_tables`` joins two such tables
on ``case_id``; ``pair_runs`` does both and applies the missing-value rules; ``slice_members``
answers "which paired cases are in this slice" (round 9 X3.6).

The slice columns of a ``ScoreTable`` are strings: ``perturbation`` is ``""`` for an unperturbed
case and ``tags`` joins a case's tags with ``"|"``.
"""

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from pydantic import ValidationError

from pruefstand.core.models.gate import ScoreTable
from pruefstand.core.models.metric import MetricStatus
from pruefstand.core.models.run import RunResults, ScoredCase
from pruefstand.gate._cases import cut_ids, fillable, judge_side, lookup, request_failed
from pruefstand.gate._validate import fail

OVERALL = "overall"
PERTURBED_ALL = "perturbed_all"
DIMENSIONS = ("category", "perturbation", "tenant", "lang", "tags")
TAG_SEP = "|"


@dataclass(frozen=True, eq=False)
class Universe:
    """Slice columns of every case both runs hold, and which have a baseline ``error``."""

    attrs: dict[str, tuple[str, ...]]
    base_error: NDArray[np.bool_]
    clusters: NDArray[np.str_]


@dataclass(frozen=True, eq=False)
class PairedTable:
    """Two runs paired on ``case_id`` for one metric (rows sorted by case id).

    ``diffs`` is candidate minus baseline, negated when lower is better (negative = worse);
    ``base_values`` and ``cand_values`` stay unoriented (a worst-filled candidate value included).
    ``cluster_ids`` and ``attrs`` (slice columns) come from the candidate's cases.
    """

    metric: str
    higher_is_better: bool
    case_ids: tuple[str, ...]
    cluster_ids: NDArray[np.str_]
    diffs: NDArray[np.float64]
    base_values: NDArray[np.float64]
    cand_values: NDArray[np.float64]
    attrs: dict[str, tuple[str, ...]]
    n_unmatched: int
    n_excluded: int
    n_worst_filled: int
    judge_error: NDArray[np.bool_]
    all_attrs: dict[str, tuple[str, ...]]
    all_base_error: NDArray[np.bool_]
    all_clusters: NDArray[np.str_]


def _columns(scored: Iterable[ScoredCase]) -> dict[str, tuple[str, ...]]:
    cases = [s.case for s in scored]
    return {
        "category": tuple(c.category.value for c in cases),
        "perturbation": tuple(c.perturbation or "" for c in cases),
        "tenant": tuple(str(c.tenant) for c in cases),
        "lang": tuple(c.lang.value for c in cases),
        "tags": tuple(TAG_SEP.join(c.tags) for c in cases),
    }


def _build(
    run: RunResults,
    metric: str,
    *,
    higher_is_better: bool,
    fill_worst: bool,
    fill_errors: bool = False,
    cut: frozenset[str] = frozenset(),
    flagged: frozenset[str] = frozenset(),
) -> tuple[ScoreTable, frozenset[str], frozenset[str]]:
    worst = 0.0 if higher_is_better else 1.0
    kept: list[ScoredCase] = []
    values: list[float] = []
    filled: set[str] = set()
    errors: set[str] = set()
    for scored in run.values:
        value = lookup(scored, metric)
        case_id = str(scored.case.id)
        ok = value is not None and value.status is MetricStatus.OK and value.value is not None
        if ok and value is not None and value.value is not None and case_id not in cut:
            values.append(value.value)
        elif fill_worst and (case_id in cut or fillable(scored, value, fill_errors=fill_errors)):
            values.append(worst)
            filled.add(case_id)
            if case_id in flagged or (judge_side(value) and not request_failed(scored)):
                errors.add(case_id)
        else:
            continue
        kept.append(scored)
    try:
        table = ScoreTable(
            metric=metric,
            higher_is_better=higher_is_better,
            case_ids=tuple(s.case.id for s in kept),
            cluster_ids=tuple(s.case.cluster_id for s in kept),
            values=tuple(values),
            slices=_columns(kept),
        )
    except ValidationError as exc:
        reason = exc.errors()[0]["msg"]
        fail(f"run {run.manifest.run_id}: cannot build a score table for {metric}: {reason}")
    return table, frozenset(filled), frozenset(errors)


def score_table(
    run: RunResults, metric: str, *, higher_is_better: bool, fill_worst: bool = False
) -> ScoreTable:
    """Return the values of ``metric`` in ``run`` as a ``ScoreTable`` (one per metric and run).

    Only cases with status ``ok`` are listed, in run order. With ``fill_worst`` (the candidate's
    table) a case without a number gets the worst value (0.0 if higher is better, else 1.0) when
    it is ``not_applicable``, absent, or an ``error`` on a request that failed
    (``error_rate == 1``); a judge error on a successful request stays out (W3.9).

    Args:
        run: The run.
        metric: Metric name.
        higher_is_better: Direction of the metric.
        fill_worst: Fill as described above.

    Returns:
        The table.

    Raises:
        GateInputError: ``run`` repeats a ``case_id``.
    """
    return _build(run, metric, higher_is_better=higher_is_better, fill_worst=fill_worst)[0]


def pair_tables(
    base: ScoreTable,
    cand: ScoreTable,
    *,
    filled: frozenset[str] = frozenset(),
    judge_errors: frozenset[str] = frozenset(),
    universe: Universe | None = None,
    n_unmatched: int = 0,
    n_shared: int | None = None,
) -> PairedTable:
    """Join two ``ScoreTable`` s on ``case_id`` (rows sorted by case id).

    Args:
        base: Baseline table.
        cand: Candidate table; its cluster ids and slice columns are used.
        filled: Case ids whose candidate value was worst-filled (for ``n_worst_filled``).
        universe: Slice columns and baseline-error flags of every case both runs hold (default:
            the paired rows), so slices without baseline values are still listed.
        judge_errors: Case ids among ``filled`` that are judge errors on a successful request;
            they are flagged in ``judge_error`` and the caller decides per slice (exclude or fill).
        n_unmatched: Number of cases in only one run (counted by the caller).
        n_shared: Number of cases in both runs; default: the cases both tables list. The
            difference to the paired count is ``n_excluded``.

    Returns:
        The paired table.

    Raises:
        GateInputError: The tables are for different metrics or directions.
    """
    if (base.metric, base.higher_is_better) != (cand.metric, cand.higher_is_better):
        fail("cannot pair score tables of different metrics or directions")
    position = {case_id: i for i, case_id in enumerate(base.case_ids)}
    rows = sorted((cid, j) for j, cid in enumerate(cand.case_ids) if cid in position)
    cand_idx = np.array([j for _, j in rows], dtype=np.intp)
    base_idx = np.array([position[cid] for cid, _ in rows], dtype=np.intp)
    base_values = np.asarray(base.values, dtype=np.float64)[base_idx]
    cand_values = np.asarray(cand.values, dtype=np.float64)[cand_idx]
    sign = 1.0 if cand.higher_is_better else -1.0
    case_ids = tuple(str(cid) for cid, _ in rows)
    cand_clusters = [cand.cluster_ids[j] for j in cand_idx]
    attrs = {k: tuple(v[j] for j in cand_idx) for k, v in cand.slices.items()}
    shared = n_shared if n_shared is not None else len(case_ids)
    return PairedTable(
        metric=cand.metric,
        higher_is_better=cand.higher_is_better,
        case_ids=case_ids,
        cluster_ids=np.asarray(cand_clusters, dtype=np.str_),
        diffs=sign * (cand_values - base_values),
        base_values=base_values,
        cand_values=cand_values,
        attrs=attrs,
        n_unmatched=n_unmatched,
        n_excluded=shared - len(case_ids),
        n_worst_filled=len((filled - judge_errors).intersection(case_ids)),
        judge_error=np.array([cid in judge_errors for cid in case_ids], dtype=np.bool_),
        all_attrs=universe.attrs if universe else attrs,
        all_base_error=universe.base_error if universe else np.zeros(len(case_ids), dtype=np.bool_),
        all_clusters=universe.clusters if universe else np.asarray(cand_clusters, dtype=np.str_),
    )


def _universe(base: RunResults, cand: RunResults, metric: str, shared: list[str]) -> Universe:
    """Slice columns of the shared cases and which of them have a baseline ``error``."""
    by_id = {str(sc.case.id): sc for sc in cand.values}
    base_bad = {
        str(sc.case.id)
        for sc in base.values
        if (v := lookup(sc, metric)) is not None and v.status is MetricStatus.ERROR
    }
    return Universe(
        attrs=_columns(by_id[i] for i in shared),
        base_error=np.array([i in base_bad for i in shared], dtype=np.bool_),
        clusters=np.asarray([by_id[i].case.cluster_id for i in shared], dtype=np.str_),
    )


def pair_runs(
    base: RunResults, cand: RunResults, metric: str, *, higher_is_better: bool
) -> PairedTable:
    """Pair two runs for one metric (T1.7 step 3).

    Rows are the cases whose baseline value is ``ok`` and that both runs hold (cases in one run
    only: ``n_unmatched``; baseline not ``ok``: ``n_excluded``). A candidate ``not_applicable`` or
    request error gets the worst value (``n_worst_filled``). A candidate ``error`` on a
    successful request (a judge error) also carries the worst value but is flagged in
    ``judge_error``: ``gate.pairs`` excludes the flagged rows of a slice unless they are more
    than 20 % of it (W3.9), so a slice cannot vanish through judge errors.

    A candidate value computed on a truncated judge input (``details["truncated"]``) counts
    against the candidate when the baseline's input fit (worst value, never informational); when
    the baseline was truncated on that case too it is flagged like a judge error (excluded under
    the 20 % cap, worst-filled beyond it).

    Args:
        base: Baseline run.
        cand: Candidate run.
        metric: Metric name.
        higher_is_better: Direction of the metric.

    Returns:
        The paired table, diffs oriented so that negative = worse.

    Raises:
        GateInputError: A run repeats a ``case_id``.
    """
    base_ids = {str(s.case.id) for s in base.values}
    cand_ids = {str(s.case.id) for s in cand.values}
    base_table = score_table(base, metric, higher_is_better=higher_is_better)
    base_cut, cand_cut = cut_ids(base, metric), cut_ids(cand, metric)
    cand_table, filled, errors = _build(
        cand,
        metric,
        higher_is_better=higher_is_better,
        fill_worst=True,
        fill_errors=True,
        cut=cand_cut,  # truncated on the candidate side: worst-filled when the baseline fit,
        flagged=cand_cut & base_cut,  # and capped like a judge error when both were truncated
    )
    universe = _universe(base, cand, metric, sorted(base_ids & cand_ids))
    return pair_tables(
        base_table,
        cand_table,
        filled=filled,
        judge_errors=errors,
        universe=universe,
        n_unmatched=len(base_ids ^ cand_ids),
        n_shared=len(base_ids & cand_ids),
    )

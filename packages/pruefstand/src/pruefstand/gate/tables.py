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
from pruefstand.core.models.metric import MetricStatus, MetricValue
from pruefstand.core.models.run import RunResults, ScoredCase
from pruefstand.gate._validate import fail

OVERALL = "overall"
PERTURBED_ALL = "perturbed_all"
DIMENSIONS = ("category", "perturbation", "tenant", "lang", "tags")
TAG_SEP = "|"
MAX_EXCLUDED_FRACTION = 0.20  # more judge errors than this share are worst-filled, not excluded


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


def _lookup(scored: ScoredCase, metric: str) -> MetricValue | None:
    for value in scored.values:
        if value.metric == metric:
            return value
    return None


def _request_failed(scored: ScoredCase) -> bool:
    value = _lookup(scored, "error_rate")
    return value is not None and value.value is not None and value.value >= 1.0


def _fillable(scored: ScoredCase, value: MetricValue | None, *, fill_errors: bool) -> bool:
    """A candidate value without a number is worst-filled unless it is a judge error."""
    if value is None or value.status is MetricStatus.NOT_APPLICABLE:
        return True
    return value.status is MetricStatus.ERROR and (fill_errors or _request_failed(scored))


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
) -> tuple[ScoreTable, frozenset[str]]:
    worst = 0.0 if higher_is_better else 1.0
    kept: list[ScoredCase] = []
    values: list[float] = []
    filled: set[str] = set()
    for scored in run.values:
        value = _lookup(scored, metric)
        if value is not None and value.status is MetricStatus.OK and value.value is not None:
            values.append(value.value)
        elif fill_worst and _fillable(scored, value, fill_errors=fill_errors):
            values.append(worst)
            filled.add(str(scored.case.id))
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
    return table, frozenset(filled)


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
    n_unmatched: int = 0,
    n_shared: int | None = None,
) -> PairedTable:
    """Join two ``ScoreTable`` s on ``case_id`` (rows sorted by case id).

    Args:
        base: Baseline table.
        cand: Candidate table; its cluster ids and slice columns are used.
        filled: Case ids whose candidate value was worst-filled (for ``n_worst_filled``).
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
    shared = n_shared if n_shared is not None else len(case_ids)
    return PairedTable(
        metric=cand.metric,
        higher_is_better=cand.higher_is_better,
        case_ids=case_ids,
        cluster_ids=np.asarray([cand.cluster_ids[j] for j in cand_idx], dtype=np.str_),
        diffs=sign * (cand_values - base_values),
        base_values=base_values,
        cand_values=cand_values,
        attrs={k: tuple(v[j] for j in cand_idx) for k, v in cand.slices.items()},
        n_unmatched=n_unmatched,
        n_excluded=shared - len(case_ids),
        n_worst_filled=len(filled.intersection(case_ids)),
    )


def pair_runs(
    base: RunResults, cand: RunResults, metric: str, *, higher_is_better: bool
) -> PairedTable:
    """Pair two runs for one metric (T1.7 step 3).

    Cases in only one run are excluded and counted (``n_unmatched``). A baseline value that is not
    ``ok`` excludes the pair; a candidate ``error`` on a successful request (a judge error) excludes
    it as well (``n_excluded``, never worst-filled) unless more than ``MAX_EXCLUDED_FRACTION`` of
    the baseline-``ok`` cases would go that way, then they are worst-filled; a candidate
    ``not_applicable`` or request error against an ``ok`` baseline gets the worst value
    (``n_worst_filled``).

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
    cand_table, filled = _build(cand, metric, higher_is_better=higher_is_better, fill_worst=True)
    comparable = set(base_table.case_ids) & cand_ids
    dropped = comparable - set(cand_table.case_ids)  # candidate judge errors, excluded
    if len(dropped) > MAX_EXCLUDED_FRACTION * len(comparable) + 1e-9:
        cand_table, filled = _build(
            cand, metric, higher_is_better=higher_is_better, fill_worst=True, fill_errors=True
        )
    return pair_tables(
        base_table,
        cand_table,
        filled=filled,
        n_unmatched=len(base_ids ^ cand_ids),
        n_shared=len(base_ids & cand_ids),
    )


def _column(table: PairedTable, dimension: str) -> NDArray[np.str_]:
    if dimension not in table.attrs:
        fail(f"unknown slice dimension {dimension!r}")
    return np.asarray(table.attrs[dimension], dtype=np.str_)


def slice_members(table: PairedTable, dimension: str, value: str) -> NDArray[np.bool_]:
    """Return the mask of paired cases in a slice (round 9 X3.6).

    ``overall``, ``tenant``, ``lang``, ``category`` and ``tags`` hold unperturbed cases only;
    ``perturbed_all`` and ``perturbation=<p>`` hold perturbed cases only.

    Args:
        table: The paired table.
        dimension: ``overall``, ``perturbed_all`` or one of ``category``, ``perturbation``,
            ``tenant``, ``lang``, ``tags``.
        value: The slice value (ignored for ``overall`` and ``perturbed_all``).

    Returns:
        A boolean mask over the rows of ``table``.

    Raises:
        GateInputError: Unknown ``dimension``.
    """
    perturbed = np.asarray(_column(table, "perturbation") != "", dtype=np.bool_)
    if dimension == OVERALL:
        return np.asarray(~perturbed, dtype=np.bool_)
    if dimension == PERTURBED_ALL:
        return perturbed
    if dimension == "perturbation":
        return np.asarray(_column(table, "perturbation") == value, dtype=np.bool_)
    if dimension == "tags":
        tagged = np.fromiter(
            (value in tags.split(TAG_SEP) for tags in table.attrs["tags"]),
            dtype=np.bool_,
            count=len(table.case_ids),
        )
        return np.asarray(tagged & ~perturbed, dtype=np.bool_)
    return np.asarray((_column(table, dimension) == value) & ~perturbed, dtype=np.bool_)


def slice_values(table: PairedTable, dimension: str) -> tuple[str, ...]:
    """Return the sorted distinct values of ``dimension`` among the paired cases that can be in it.

    Args:
        table: The paired table.
        dimension: One of ``category``, ``perturbation``, ``tenant``, ``lang``, ``tags``.

    Returns:
        The values (``perturbation``: of perturbed cases; the others: of unperturbed cases).

    Raises:
        GateInputError: Unknown ``dimension``.
    """
    perturbed = _column(table, "perturbation") != ""
    column = _column(table, dimension)
    if dimension == "perturbation":
        return tuple(sorted({str(v) for v in column[perturbed]}))
    if dimension == "tags":
        tags = {t for cell in column[~perturbed] for t in str(cell).split(TAG_SEP) if t}
        return tuple(sorted(tags))
    return tuple(sorted({str(v) for v in column[~perturbed]}))

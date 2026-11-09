"""Slice membership of paired cases (T1.7 step 4, round 9 X3.6).

``slice_members`` works on the paired rows (baseline value ``ok``); ``universe_members`` and
``slice_values`` work on every case both runs hold, so a slice whose baseline values are all
missing is still listed (and shows as ``INSUFFICIENT_DATA``) instead of vanishing.
"""

import numpy as np
from numpy.typing import NDArray

from pruefstand.core.config import GatePolicy
from pruefstand.gate._validate import fail
from pruefstand.gate.tables import OVERALL, PERTURBED_ALL, TAG_SEP, PairedTable

Attrs = dict[str, tuple[str, ...]]
RETRIEVAL_METRICS = ("context_recall", "ndcg_at_k")  # the only metrics with a `perturbed_all` pair


def _column(attrs: Attrs, dimension: str) -> NDArray[np.str_]:
    if dimension not in attrs:
        fail(f"unknown slice dimension {dimension!r}")
    return np.asarray(attrs[dimension], dtype=np.str_)


def _members(attrs: Attrs, dimension: str, value: str) -> NDArray[np.bool_]:
    perturbed = np.asarray(_column(attrs, "perturbation") != "", dtype=np.bool_)
    if dimension == OVERALL:
        return np.asarray(~perturbed, dtype=np.bool_)
    if dimension == PERTURBED_ALL:
        return perturbed
    if dimension == "perturbation":
        return np.asarray(_column(attrs, "perturbation") == value, dtype=np.bool_)
    if dimension == "tags":
        tagged = np.fromiter(
            (value in tags.split(TAG_SEP) for tags in attrs["tags"]),
            dtype=np.bool_,
            count=perturbed.size,
        )
        return np.asarray(tagged & ~perturbed, dtype=np.bool_)
    return np.asarray((_column(attrs, dimension) == value) & ~perturbed, dtype=np.bool_)


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
    return _members(table.attrs, dimension, value)


def universe_members(table: PairedTable, dimension: str, value: str) -> NDArray[np.bool_]:
    """Like ``slice_members`` but over every case both runs hold (``table.all_attrs``)."""
    return _members(table.all_attrs, dimension, value)


def slice_values(table: PairedTable, dimension: str) -> tuple[str, ...]:
    """Return the sorted distinct values of ``dimension`` among all cases that can be in it.

    Args:
        table: The paired table.
        dimension: One of ``category``, ``perturbation``, ``tenant``, ``lang``, ``tags``.

    Returns:
        The values (``perturbation``: of perturbed cases; the others: of unperturbed cases),
        taken from every case both runs hold, not only the paired ones.

    Raises:
        GateInputError: Unknown ``dimension``.
    """
    perturbed = _column(table.all_attrs, "perturbation") != ""
    column = _column(table.all_attrs, dimension)
    if dimension == "perturbation":
        return tuple(sorted({str(v) for v in column[perturbed]}))
    if dimension == "tags":
        tags = {t for cell in column[~perturbed] for t in str(cell).split(TAG_SEP) if t}
        return tuple(sorted(tags))
    return tuple(sorted({str(v) for v in column[~perturbed]}))


def slice_specs(table: PairedTable, policy: GatePolicy) -> list[tuple[str, str]]:
    """Return the (dimension, value) pairs of one metric in the contractual order (step 6).

    ``overall``; ``perturbed_all`` only for ``RETRIEVAL_METRICS`` when the run has perturbed
    members; then every value of each ``policy.slices`` dimension. The one definition used by the
    pairing (``gate.pairs``) and by the promote-time baseline check (``gate.baseline_run``).

    Args:
        table: The paired table of the metric.
        policy: Gate policy (``slices``).

    Returns:
        The pairs, in order.
    """
    specs: list[tuple[str, str]] = [(OVERALL, OVERALL)]
    if (
        table.metric in RETRIEVAL_METRICS
        and slice_members(table, PERTURBED_ALL, PERTURBED_ALL).any()
    ):
        specs.append((PERTURBED_ALL, PERTURBED_ALL))
    for dimension in policy.slices:
        specs.extend((dimension, value) for value in slice_values(table, dimension))
    return specs

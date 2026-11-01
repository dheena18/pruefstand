"""Slice membership of paired cases (T1.7 step 4, round 9 X3.6)."""

import numpy as np
from numpy.typing import NDArray

from pruefstand.gate._validate import fail
from pruefstand.gate.tables import OVERALL, PERTURBED_ALL, TAG_SEP, PairedTable


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

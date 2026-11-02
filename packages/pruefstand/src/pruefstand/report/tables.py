"""One table rule for every ``SliceDecision`` (ui-spec §11.1, interfaces §9, X5.4).

``assign_table`` answers which of the three tables a decision belongs to; ``assign_block`` lays it
out in one of the blocks G, A, C, R, J, I, N. Both are pure and shared by the PR comment (T1.9),
the HTML report (T6.4) and mirrored by the dashboard (T8.2a).
"""

from enum import StrEnum
from typing import Literal

from pruefstand.core.models.gate import SliceDecision

Source = Literal["decisions", "absolute_checks", "notable_slices"]
Stack = Literal["live", "a40"]
NO_REASON = "–"


class Table(StrEnum):
    """The three tables of ui-spec §11.1 (first match wins)."""

    GATED = "gated"
    INFORMATIONAL = "informational"
    NOTABLE = "notable"


class Block(StrEnum):
    """The layout blocks of ui-spec §11.1."""

    G = "G"
    A = "A"
    C = "C"
    R = "R"
    J = "J"
    I = "I"  # noqa: E741  (block letter of ui-spec §11.1)
    N = "N"


REPORTED_REASONS = frozenset(
    {"tier1_deterministic_only", "tier1_injection_reported", "applicable_clusters<30"}
)
JUDGED_REASON = "tier1_judged"


def reason_code(decision: SliceDecision) -> str:
    """Return the ``informational_reason`` of ``decision``, or ``–`` when it has none."""
    return decision.informational_reason or NO_REASON


def assign_table(decision: SliceDecision, source: Source) -> Table:
    """Return the one table ``decision`` belongs to.

    Args:
        decision: A row of ``GateReport.decisions``, ``absolute_checks`` or ``notable_slices``.
        source: The list ``decision`` comes from.

    Returns:
        ``GATED`` for ``gated`` rows without a reason (incl. ``INSUFFICIENT_DATA``),
        ``INFORMATIONAL`` for any row with a reason, ``NOTABLE`` for a ``notable_slices`` row
        matching neither. A row that matches none is a gate bug and is returned as
        ``INFORMATIONAL`` (its reason reads ``–``, see ``reason_code``), never dropped
        here; the PR comment omits such rows from its Informational line (D387).

    Example:
        >>> from pruefstand.core.enums import GateStatus
        >>> row = SliceDecision(metric="m", dimension="overall", value="overall",
        ...     status=GateStatus.PASS, gated=True, baseline_mean=0.5, candidate_mean=0.5,
        ...     result=None, p_adjusted=None, mde=None)
        >>> assign_table(row, "decisions").value
        'gated'
    """
    if decision.informational_reason is not None:
        return Table.INFORMATIONAL
    if decision.gated:
        return Table.GATED
    return Table.NOTABLE if source == "notable_slices" else Table.INFORMATIONAL


def assign_block(decision: SliceDecision, source: Source, stack: Stack) -> Block:
    """Return the layout block of ``decision`` for the tier given by ``stack``.

    Tier 1 (``live``) lays out reported rows as ``R`` and judged rows as ``J``; in tier 2 both are
    part of ``I``. Gated absolute checks are ``C`` (tier 1) or ``A`` (tier 2).
    """
    table = assign_table(decision, source)
    if table is Table.NOTABLE:
        return Block.N
    if table is Table.GATED:
        if source == "absolute_checks":
            return Block.C if stack == "live" else Block.A
        return Block.G
    reason = decision.informational_reason
    if stack == "live" and reason in REPORTED_REASONS:
        return Block.R
    if stack == "live" and reason == JUDGED_REASON:
        return Block.J
    return Block.I

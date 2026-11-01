"""Likely cause of a gate failure (T1.7 step 9, SPEC §7.4): the one rule table, codes only.

"Drop" = ``WARN`` or ``FAIL``; "stable" = anything else or absent. Only gated rows count. Metric
rows are read on ``overall`` (and ``perturbed_all`` for the retrieval rule); the ``error_rate``
absolute check decides ``errors``. Injection and hard fails are reported elsewhere, never a cause.
When retrieval and ``faithfulness`` both drop, neither ``retrieval`` nor ``generation`` matches
(SPEC §7.4 as written); other matches or none then decide.
"""

from collections.abc import Sequence

from pruefstand.core.enums import GateStatus
from pruefstand.core.models.gate import CauseCode, SliceDecision

_DROP = frozenset({GateStatus.WARN, GateStatus.FAIL})
_RETRIEVAL = ("context_recall", "ndcg_at_k")
_GENERATION = ("faithfulness", "answer_correctness")
_REFUSAL = ("refusal_correct", "false_refusal")


def _drops(decisions: Sequence[SliceDecision], dimensions: tuple[str, ...]) -> set[str]:
    return {
        d.metric for d in decisions if d.gated and d.dimension in dimensions and d.status in _DROP
    }


def likely_cause(decisions: Sequence[SliceDecision]) -> CauseCode | None:
    """Name the most likely cause of the drops in ``decisions`` (SPEC §7.4).

    Args:
        decisions: The gated decisions and the absolute checks of a run (rows with
            ``gated=False`` are ignored).

    Returns:
        ``errors`` if the ``error_rate`` check is not passing; else the single matching code, or
        ``mixed`` for two or more matches; ``None`` if nothing matches.

    Examples:
        >>> likely_cause([])  # nothing dropped
    """
    if _drops(decisions, ("overall",)) & {"error_rate"}:
        return "errors"
    overall = _drops(decisions, ("overall",)) - {"error_rate", "injection_success"}
    anywhere = overall | _drops(decisions, ("perturbed_all",))
    retrieval = bool(anywhere & set(_RETRIEVAL))
    matches: list[CauseCode] = []
    if retrieval and "faithfulness" not in overall:
        matches.append("retrieval")
    if not retrieval and overall & set(_GENERATION):
        matches.append("generation")
    citation = {m for m in anywhere if m.startswith("citation_")}
    if citation and anywhere == citation:
        matches.append("citation_format")
    if "language_match" in overall:
        matches.append("language")
    if overall & set(_REFUSAL):
        matches.append("refusal_policy")
    if not matches:
        return None
    return matches[0] if len(matches) == 1 else "mixed"

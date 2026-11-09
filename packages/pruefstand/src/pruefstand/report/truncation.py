"""Which cases had a judge input truncated (X3.9): the ids behind ``counts["judge_truncated"]``."""

from pruefstand.core.config.gate import JUDGED_METRICS
from pruefstand.core.models.run import RunResults


def judge_truncated_case_ids(results: RunResults) -> list[str]:
    """Return the sorted ids of the cases with a truncated judge input.

    A case counts when a judged metric value carries ``details["truncated"] is True`` or the
    reason ``judge_input_too_long`` (the estimate path and the provider-reported cut alike).
    The ids are raw (target-independent test-case ids); callers escape them for their medium.

    Args:
        results: The candidate run.

    Returns:
        Sorted, de-duplicated case ids; empty when nothing was cut.
    """
    return sorted(
        {
            str(s.case.id)
            for s in results.values
            for v in s.values
            if v.metric in JUDGED_METRICS
            and (
                v.details.get("truncated") is True
                or v.details.get("reason") == "judge_input_too_long"
            )
        }
    )

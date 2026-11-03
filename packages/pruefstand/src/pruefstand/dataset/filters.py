"""Public entry point of the QA filters (T4.3, interfaces §14): re-exports every filter.

The code lives in ``filters_support`` (support check, near-duplicates), ``filters_text`` (copy
rules, "der Text" rule), ``filters_checks`` (evidence, cluster overlap, style report) and
``filters_run`` (``filter_candidates``), each below the 300-line limit.
"""

from pruefstand.core.models.dataset import FilterConfig, FilterResult
from pruefstand.dataset.filters_checks import (
    StyleReport,
    check_evidence,
    drop_cluster_overlap,
    style_report,
)
from pruefstand.dataset.filters_run import (
    Dropped,
    FilterOutcome,
    FilterReport,
    SupportSetup,
    filter_candidates,
)
from pruefstand.dataset.filters_support import (
    Embedder,
    check_support,
    check_support_family,
    dedupe,
    dedupe_report,
)
from pruefstand.dataset.filters_text import check_overlap

__all__ = [
    "Dropped",
    "Embedder",
    "FilterConfig",
    "FilterOutcome",
    "FilterReport",
    "FilterResult",
    "StyleReport",
    "SupportSetup",
    "check_evidence",
    "check_overlap",
    "check_support",
    "check_support_family",
    "dedupe",
    "dedupe_report",
    "drop_cluster_overlap",
    "filter_candidates",
    "style_report",
]

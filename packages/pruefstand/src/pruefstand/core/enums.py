"""Closed vocabularies of the data model (interfaces §2). Values are lower-case snake_case."""

from enum import StrEnum

from pruefstand.core.models.metric import MetricKind, MetricStatus

__all__ = [
    "Category",
    "Difficulty",
    "GateStatus",
    "Lang",
    "MetricKind",
    "MetricStatus",
    "Split",
]


class Lang(StrEnum):
    """Language of a question or chunk."""

    DE = "de"
    EN = "en"


class Category(StrEnum):
    """Kind of test case."""

    FACTUAL = "factual"
    MULTI_HOP = "multi_hop"
    COMPARISON = "comparison"
    UNANSWERABLE = "unanswerable"
    CROSS_LINGUAL = "cross_lingual"
    INJECTION = "injection"
    LEAK_PROBE = "leak_probe"
    SYSTEM_PROMPT_EXTRACTION = "system_prompt_extraction"
    FILTER_BYPASS = "filter_bypass"


class Difficulty(StrEnum):
    """Annotated difficulty of a test case."""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class Split(StrEnum):
    """Dataset split (sizes and selection rules: interfaces §2 and §14)."""

    SMOKE = "smoke"
    SMOKE_LIVE = "smoke_live"
    CORE = "core"
    ROBUST_PR = "robust_pr"
    FULL = "full"
    HUMAN_LABELS = "human_labels"
    RQ1 = "rq1"


class GateStatus(StrEnum):
    """Decision of the gate; ``UNSUPPORTED_CONFIG`` counts as ``WARN``."""

    PASS = "pass"  # noqa: S105  (a status word, not a credential)
    WARN = "warn"
    FAIL = "fail"
    INSUFFICIENT_DATA = "insufficient_data"
    UNSUPPORTED_CONFIG = "unsupported_config"

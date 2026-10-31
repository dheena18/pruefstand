from enum import StrEnum

import pytest

from pruefstand.core import enums
from pruefstand.core.enums import Category, Difficulty, GateStatus, Lang, Split
from pruefstand.core.models import metric

TABLE: list[tuple[type[StrEnum], dict[str, str]]] = [
    (Lang, {"DE": "de", "EN": "en"}),
    (
        Category,
        {
            "FACTUAL": "factual",
            "MULTI_HOP": "multi_hop",
            "COMPARISON": "comparison",
            "UNANSWERABLE": "unanswerable",
            "CROSS_LINGUAL": "cross_lingual",
            "INJECTION": "injection",
            "LEAK_PROBE": "leak_probe",
            "SYSTEM_PROMPT_EXTRACTION": "system_prompt_extraction",
            "FILTER_BYPASS": "filter_bypass",
        },
    ),
    (Difficulty, {"EASY": "easy", "MEDIUM": "medium", "HARD": "hard"}),
    (
        Split,
        {
            "SMOKE": "smoke",
            "SMOKE_LIVE": "smoke_live",
            "CORE": "core",
            "ROBUST_PR": "robust_pr",
            "FULL": "full",
            "HUMAN_LABELS": "human_labels",
            "RQ1": "rq1",
        },
    ),
    (metric.MetricStatus, {"OK": "ok", "NOT_APPLICABLE": "not_applicable", "ERROR": "error"}),
    (metric.MetricKind, {"DETERMINISTIC": "deterministic", "JUDGED": "judged"}),
    (
        GateStatus,
        {
            "PASS": "pass",
            "WARN": "warn",
            "FAIL": "fail",
            "INSUFFICIENT_DATA": "insufficient_data",
            "UNSUPPORTED_CONFIG": "unsupported_config",
        },
    ),
]
ROWS = [(cls, name, value) for cls, members in TABLE for name, value in members.items()]


@pytest.mark.parametrize(("cls", "name", "value"), ROWS)
def test_serialised_value(cls: type[StrEnum], name: str, value: str) -> None:
    member = cls[name]
    assert member.value == value
    assert cls(value) is member
    assert str(member) == value


@pytest.mark.parametrize(("cls", "members"), TABLE)
def test_no_member_missing_from_table(cls: type[StrEnum], members: dict[str, str]) -> None:
    assert {m.name for m in cls} == set(members)


def test_named_values() -> None:
    assert Split.SMOKE_LIVE.value == "smoke_live"
    assert Split.ROBUST_PR.value == "robust_pr"
    assert Split.RQ1.value == "rq1"
    assert GateStatus.INSUFFICIENT_DATA.value == "insufficient_data"
    assert GateStatus.UNSUPPORTED_CONFIG.value == "unsupported_config"
    assert Category.MULTI_HOP.value == "multi_hop"


def test_metric_enums_are_reexported() -> None:
    assert enums.MetricStatus is metric.MetricStatus
    assert enums.MetricKind is metric.MetricKind


def test_unknown_value_is_an_error() -> None:
    with pytest.raises(ValueError, match="nope"):
        Split("nope")

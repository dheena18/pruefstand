"""ScoreTable and BootstrapResult (interfaces §9, ``core.models.gate``)."""

import pytest
from pydantic import ValidationError

from pruefstand.core.ids import CaseId
from pruefstand.core.models.gate import BootstrapResult, ScoreTable


def _table(**over: object) -> ScoreTable:
    data: dict[str, object] = {
        "metric": "answer_correctness",
        "higher_is_better": True,
        "case_ids": (CaseId("c1"), CaseId("c2"), CaseId("c3")),
        "cluster_ids": ("d1", "d1", "d2"),
        "values": (1.0, 0.0, 0.5),
        "slices": {"tenant": ("a", "a", "b")},
    }
    data.update(over)
    return ScoreTable.model_validate(data)


def _result(**over: object) -> BootstrapResult:
    data: dict[str, object] = {
        "mean_diff": -0.06,
        "ci_low": -0.1,
        "ci_high": -0.02,
        "p_value": 0.01,
        "method": "bootstrap",
        "se": 0.02,
        "n_cases": 40,
        "n_clusters": 30,
        "n_resamples": 2000,
        "confidence": 0.95,
    }
    data.update(over)
    return BootstrapResult.model_validate(data)


def test_score_table_valid() -> None:
    t = _table()
    assert t.slices["tenant"] == ("a", "a", "b")
    assert len(t.values) == 3


@pytest.mark.parametrize(
    "over",
    [
        {"values": (1.0, 0.0)},
        {"cluster_ids": ("d1",)},
        {"slices": {"tenant": ("a", "a")}},
    ],
)
def test_score_table_length_mismatch(over: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _table(**over)


def test_score_table_frozen() -> None:
    t = _table()
    with pytest.raises(ValidationError):
        t.metric = "other"  # type: ignore[misc]  # frozen model


def test_score_table_roundtrip_umlaut() -> None:
    t = _table(slices={"category": ("Kündigung", "Kündigung", "„Frist“")})
    assert ScoreTable.model_validate_json(t.model_dump_json()) == t


def test_score_table_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        _table(bogus=1)


def test_bootstrap_result_roundtrip() -> None:
    r = _result()
    assert BootstrapResult.model_validate_json(r.model_dump_json()) == r


def test_bootstrap_result_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        _result(bogus=1)


@pytest.mark.parametrize(
    "over",
    [
        {"p_value": 1.5},
        {"p_value": float("nan")},
        {"mean_diff": float("inf")},
        {"n_clusters": 0},
        {"n_clusters": 41},
        {"n_resamples": 0},
        {"confidence": 1.0},
        {"method": "wilcoxon"},
    ],
)
def test_bootstrap_result_rejects_invalid(over: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _result(**over)

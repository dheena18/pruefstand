import pytest

from pruefstand.core import errors
from pruefstand.core.errors import LLMError, PruefstandError, QuotaExhausted, TargetError

NAMES = [
    "ConfigError",
    "TargetError",
    "LLMError",
    "PolicyViolation",
    "BudgetExceeded",
    "QuotaExhausted",
    "DatasetError",
    "StoreError",
    "GateInputError",
    "PromptError",
    "CorpusMismatch",
]


@pytest.mark.parametrize("name", NAMES)
def test_subclass_of_pruefstand_error(name: str) -> None:
    assert issubclass(getattr(errors, name), PruefstandError)


def test_llm_error_family() -> None:
    assert issubclass(errors.PolicyViolation, LLMError)
    assert issubclass(QuotaExhausted, LLMError)


def test_base_is_an_exception() -> None:
    assert issubclass(PruefstandError, Exception)


def test_target_error_transient_flag() -> None:
    assert TargetError("x", transient=True).transient is True
    assert TargetError("x").transient is False
    assert str(TargetError("boom")) == "boom"

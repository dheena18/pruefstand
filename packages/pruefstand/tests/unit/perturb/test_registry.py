"""Registry of the deterministic perturbations (T4.4)."""

import pytest

from pruefstand.core.errors import ConfigError
from pruefstand.core.protocols import Perturbation
from pruefstand.perturb.registry import get_perturbation, perturbation_names

NAMES = ("umlaut_translit", "eszett", "numbers", "dates", "citation_style", "abbreviations", "typos")


def test_names_are_stable_and_ordered() -> None:
    assert perturbation_names() == NAMES


@pytest.mark.parametrize("name", NAMES)
def test_each_implements_the_protocol(name: str) -> None:
    p = get_perturbation(name)
    assert isinstance(p, Perturbation)
    assert p.name == name
    assert p.uses_llm is False
    assert p.version


def test_unknown_name() -> None:
    with pytest.raises(ConfigError):
        get_perturbation("compound_split")

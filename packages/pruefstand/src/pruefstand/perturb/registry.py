"""Registry of the deterministic perturbations and ``perturb_case`` (interfaces §12)."""

import numpy as np

from pruefstand.core.errors import ConfigError, DatasetError
from pruefstand.core.models.testcase import TestCase
from pruefstand.core.protocols import Perturbation
from pruefstand.perturb.abbreviations import Abbreviations
from pruefstand.perturb.citation_style import CitationStyle
from pruefstand.perturb.dates import Dates
from pruefstand.perturb.eszett import Eszett
from pruefstand.perturb.numbers import Numbers
from pruefstand.perturb.typos import Typos
from pruefstand.perturb.umlaut_translit import UmlautTranslit

_ALL: tuple[Perturbation, ...] = (
    UmlautTranslit(),
    Eszett(),
    Numbers(),
    Dates(),
    CitationStyle(),
    Abbreviations(),
    Typos(),
)
_BY_NAME = {p.name: p for p in _ALL}


def perturbation_names() -> tuple[str, ...]:
    """Return the stable names of the registered deterministic perturbations, in fixed order."""
    return tuple(_BY_NAME)


def get_perturbation(name: str) -> Perturbation:
    """Return the registered perturbation called ``name``.

    Args:
        name: One of ``perturbation_names()``.

    Returns:
        The perturbation instance (stateless, shareable).

    Raises:
        ConfigError: if ``name`` is not registered.
    """
    try:
        return _BY_NAME[name]
    except KeyError:
        msg = f"unknown perturbation {name!r}; known: {', '.join(_BY_NAME)}"
        raise ConfigError(msg) from None


def perturb_case(case: TestCase, p: Perturbation, rng: np.random.Generator) -> TestCase | None:
    """Turn a base case into its perturbed variant.

    Only the question changes; gold fields, cluster, tenant and split are kept.

    Args:
        case: A base case (``perturbation is None``).
        p: The perturbation.
        rng: Randomness for seeded perturbations.

    Returns:
        The new case with ``id = f"{case.id}~{p.name}"``, or ``None`` when the text is unchanged.

    Raises:
        DatasetError: if ``case`` is already a perturbed case.
    """
    if case.perturbation is not None:
        msg = f"case {case.id} is already perturbed ({case.perturbation}); perturb the base case"
        raise DatasetError(msg)
    result = p.apply(case.question, rng)
    if not result.changed:
        return None
    fields = case.model_dump()
    fields.update(
        id=f"{case.id}~{p.name}",
        base_id=case.base_id,
        question=result.text,
        perturbation=p.name,
    )
    return TestCase.model_validate(fields)

"""Registry of the deterministic perturbations and ``perturb_case`` (interfaces §12)."""

import numpy as np

from pruefstand.core.errors import ConfigError, DatasetError, LLMError, QuotaExhausted
from pruefstand.core.logging import get_logger
from pruefstand.core.models.testcase import TestCase
from pruefstand.core.protocols import LLMPerturbation, Perturbation
from pruefstand.llm.client import LLMClient
from pruefstand.perturb.abbreviations import Abbreviations
from pruefstand.perturb.citation_style import CitationStyle
from pruefstand.perturb.dates import Dates
from pruefstand.perturb.eszett import Eszett
from pruefstand.perturb.numbers import Numbers
from pruefstand.perturb.rewriter import PUBLIC_TENANT, private_text
from pruefstand.perturb.typos import Typos
from pruefstand.perturb.umlaut_translit import UmlautTranslit

log = get_logger(__name__)
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
    _require_base(case)
    result = p.apply(case.question, rng)
    if not result.changed:
        return None
    return variant_case(case, p.name, result.text)


def _require_base(case: TestCase) -> None:
    if case.perturbation is not None:
        msg = f"case {case.id} is already perturbed ({case.perturbation}); perturb the base case"
        raise DatasetError(msg)


def variant_case(case: TestCase, name: str, question: str) -> TestCase:
    """Return the variant of ``case`` with a new question (id ``<id>~<name>``).

    Gold fields, ``cluster_id``, tenant and split are those of the base case (T4.1 cluster rule).
    """
    fields = case.model_dump()
    fields.update(
        id=f"{case.id}~{name}", base_id=case.base_id, question=question, perturbation=name
    )
    return TestCase.model_validate(fields)


async def perturb_case_async(
    case: TestCase, p: LLMPerturbation, llm: LLMClient, rng: np.random.Generator
) -> TestCase | None:
    """Turn a base case into its variant with an LLM-assisted perturbation.

    Args:
        case: A base case (``perturbation is None``).
        p: The perturbation (it validates its own rewrite).
        llm: Client of the rewrite model (an ``LLMClient`` at runtime).
        rng: Randomness for seeded choices.

    A case of a tenant other than ``shared_public`` carries private text: its calls are marked
    ``datagen.private_docs`` so only the local model may see it (the data guard, independent of
    the canary registry).

    Returns:
        The variant (id ``<id>~<name>``, ``base_id`` and ``cluster_id`` of the base), or ``None``
        when the rewrite was rejected, did not apply, or an ``LLMError`` ended the call (logged as
        the warning ``perturb_llm_error``).

    Raises:
        DatasetError: ``case`` is already a perturbed case.
        QuotaExhausted: The free quota is used up; the caller must stop, not skip the case.
    """
    _require_base(case)
    try:
        with private_text(private=case.tenant != PUBLIC_TENANT):
            result = await p.aapply(case.question, llm, rng)
    except QuotaExhausted:
        raise
    except LLMError as err:
        log.warning("perturb_llm_error", case=case.id, perturbation=p.name, error=str(err)[:200])
        return None
    if not result.changed:
        return None
    return variant_case(case, p.name, result.text)

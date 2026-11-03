"""Registry of the four LLM-assisted perturbations (T4.5); deterministic ones: ``registry``."""

from pruefstand.core.errors import ConfigError
from pruefstand.perturb.colloquial import Colloquial
from pruefstand.perturb.compound_split import CompoundSplit
from pruefstand.perturb.gender import Gender
from pruefstand.perturb.llm_base import LLMRewritePerturbation
from pruefstand.perturb.register import Register
from pruefstand.perturb.rewriter import Rewriter
from pruefstand.perturb.validate import RewriteValidator

_BY_NAME: dict[str, type[LLMRewritePerturbation]] = {
    "compound_split": CompoundSplit,
    "register": Register,
    "gender": Gender,
    "colloquial": Colloquial,
}


def llm_perturbation_names() -> tuple[str, ...]:
    """Return the stable names of the LLM-assisted perturbations."""
    return tuple(_BY_NAME)


def build_llm_perturbation(
    name: str, rewriter: Rewriter, validator: RewriteValidator | None = None
) -> LLMRewritePerturbation:
    """Build one LLM-assisted perturbation.

    Args:
        name: One of ``llm_perturbation_names()``.
        rewriter: The rewrite model (and optional local model).
        validator: The equivalence check (needed as soon as a model writes text).

    Returns:
        The perturbation (it holds the models, so it is not a shared singleton).

    Raises:
        ConfigError: ``name`` is not an LLM-assisted perturbation.
    """
    try:
        return _BY_NAME[name](rewriter, validator)
    except KeyError:
        msg = f"unknown LLM perturbation {name!r}; known: {', '.join(_BY_NAME)}"
        raise ConfigError(msg) from None

"""The judge-family rule at run time (round 8 W3.1, ADR-0009, ADR-0019)."""

from collections.abc import Sequence

from pruefstand.core.config import JudgeConfig, ModelRef
from pruefstand.core.errors import ConfigError
from pruefstand.core.models.target import TargetInfo
from pruefstand.llm.families import family_of


def check_judge_families(
    judges: JudgeConfig, infos: Sequence[TargetInfo], fallback: ModelRef | None = None
) -> None:
    """Refuse a judge that shares the model family of a target's generator.

    Every configured judge (PR, nightly, per-metric) is compared with the family of
    ``TargetInfo.models["generator"]`` of every target (baseline and candidate). Families come
    only from ``core/data/model_families.yaml``.

    Args:
        judges: The judge configuration.
        infos: ``/v1/info`` of the targets of the run (baseline and candidate).
        fallback: ``llm.fallback_judge`` when configured; it answers in place of a judge after a
            quota failure, so it must come from another family too.

    Raises:
        ConfigError: A judge has the generator's family, a model id matches no family, or a
            target reports no generator model. Raised before any judge call.

    Examples:
        >>> from pruefstand.core.config import ModelRef
        >>> ref = ModelRef(id="ollama/gemma3:12b", family="gemma")
        >>> check_judge_families(JudgeConfig(pr=ref, nightly=ref), [])
    """
    named = {"judge.pr": judges.pr, "judge.nightly": judges.nightly}
    named.update({f"judge.per_metric.{k}": v for k, v in judges.per_metric.items()})
    if fallback is not None:
        named["llm.fallback_judge"] = fallback
    families = {name: family_of(ref.id) for name, ref in named.items()}
    for info in infos:
        generator = info.models.get("generator")
        if not generator:
            msg = "the target reports no generator model in /v1/info; the judge family is unchecked"
            raise ConfigError(msg)
        generator_family = family_of(generator)
        clash = sorted(name for name, family in families.items() if family == generator_family)
        if clash:
            msg = (
                f"judge family rule: {', '.join(clash)} has the family '{generator_family}' of "
                f"the generator '{generator}'; a judge must come from another family"
            )
            raise ConfigError(msg)

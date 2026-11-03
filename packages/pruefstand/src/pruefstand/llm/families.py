"""Model families for the judge-family rule: ``family_of`` and the family-plan check (S8)."""

from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path

import yaml

from pruefstand.core.errors import ConfigError
from pruefstand.core.models_family import UNKNOWN, model_family

_REMOVED_ROLES = frozenset({"nightly_judge", "large"})  # ADR-0019
_MAX_BYTES = 1_000_000


def family_of(model_id: str) -> str:
    """Return the family of ``model_id`` from the single table ``core/data/model_families.yaml``.

    Raises:
        ConfigError: No pattern matches (the id is named).

    Examples:
        >>> family_of("ollama/gemma3:12b")
        'gemma'
    """
    family = model_family(model_id)
    if family == UNKNOWN:
        msg = f"model '{model_id}' matches no family pattern in core/data/model_families.yaml"
        raise ConfigError(msg)
    return family


def _plan() -> dict[str, str]:
    text = files("pruefstand.core.data").joinpath("model_families.yaml").read_text("utf-8")
    plan = yaml.safe_load(text).get("plan")
    if not isinstance(plan, dict):
        msg = "model_families.yaml: missing 'plan' block"
        raise ConfigError(msg)
    return {str(k): str(v) for k, v in plan.items()}


def _entries(catalogue: Path) -> list[dict[str, object]]:
    try:
        raw = catalogue.read_bytes()[: _MAX_BYTES + 1]
        data = yaml.safe_load(raw)
    except (OSError, yaml.YAMLError) as err:
        msg = f"catalogue {catalogue} cannot be read ({type(err).__name__})"
        raise ConfigError(msg) from err
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        msg = f"catalogue {catalogue}: missing 'models' list"
        raise ConfigError(msg)
    return [m for m in models if isinstance(m, dict)]


def validate_family_plan(catalogue: Path, *, plan: Mapping[str, str] | None = None) -> None:
    """Check the catalogue against the family plan (W3.1, ADR-0019).

    Every ``role: generator`` entry has the plan's generator family, no ``judge`` entry has it,
    no ``nightly_judge`` / ``large`` role exists, and the tier-1 judge family is not the
    generator's.

    Args:
        catalogue: ``infra/gpu/models.yaml`` or a test copy.
        plan: Override of the ``plan:`` block (default: the shipped one).

    Raises:
        ConfigError: A rule is broken (the offending entry or role is named).
    """
    rules = dict(plan) if plan is not None else _plan()
    generator = rules["generator"]
    if rules.get("judge_tier1") == generator:
        msg = f"family plan: the tier-1 judge family '{generator}' equals the generator family"
        raise ConfigError(msg)
    for entry in _entries(catalogue):
        role, mid = str(entry.get("role", "")), str(entry.get("id", ""))
        family = family_of(mid) if "family" not in entry else str(entry["family"])
        if role in _REMOVED_ROLES:
            msg = f"catalogue entry '{mid}': role '{role}' no longer exists (ADR-0019)"
            raise ConfigError(msg)
        if role == "generator" and family != generator:
            msg = f"catalogue entry '{mid}': a generator needs family '{generator}', not '{family}'"
            raise ConfigError(msg)
        if role == "judge" and family == generator:
            msg = (
                f"catalogue entry '{mid}': a judge must not have the generator family '{generator}'"
            )
            raise ConfigError(msg)

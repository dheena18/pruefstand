"""The model catalogue ``infra/gpu/models.yaml`` as rag-demo reads it (D221, R12 N2)."""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from rag_demo.errors import ConfigError
from rag_demo.models import RagConfig


class CatalogueEntry(BaseModel):
    """The fields of one catalogue entry rag-demo uses; the file has more (``extra="ignore"``)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str
    engine: str
    tag: str
    digest: str = ""
    quantization: str = ""
    family: str
    role: str
    options: dict[str, float] = {}
    option_bounds: dict[str, tuple[float, float]] = {}


def load_catalogue(path: Path) -> dict[str, CatalogueEntry]:
    """Read ``models.yaml`` into entries by catalogue id.

    Raises:
        ConfigError: The file is missing, not YAML or has an invalid entry.
    """
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        entries = [CatalogueEntry.model_validate(m) for m in data["models"]]
    except (OSError, yaml.YAMLError, KeyError, TypeError, ValidationError) as err:
        msg = f"model catalogue {path} is unreadable ({type(err).__name__})"
        raise ConfigError(msg) from None
    return {e.id: e for e in entries}


def _entry(catalogue: dict[str, CatalogueEntry], path: Path, cid: str, role: str) -> CatalogueEntry:
    entry = catalogue.get(cid)
    if entry is None:
        msg = f"catalogue_id {cid!r} is not in the catalogue {path}"
        raise ConfigError(msg)
    if entry.role != role:
        msg = f"catalogue_id {cid!r} has role {entry.role!r}, expected {role!r}"
        raise ConfigError(msg)
    return entry


def _check_options(section: str, options: dict[str, float], entry: CatalogueEntry) -> None:
    for key, value in options.items():
        if entry.options.get(key) != value:
            msg = (
                f"{section}.options.{key}={value} differs from the catalogue value "
                f"{entry.options.get(key)} of {entry.id} (Y3.2: load-time options are fixed)"
            )
            raise ConfigError(msg)


def _check_bound(name: str, value: float, bounds: tuple[float, float] | None) -> None:
    if bounds is not None and not bounds[0] <= value <= bounds[1]:
        msg = (
            f"generation.{name}={value} is outside the catalogue option_bounds "
            f"[{bounds[0]}, {bounds[1]}] (N2)"
        )
        raise ConfigError(msg)


def check_against_catalogue(
    cfg: RagConfig, catalogue: dict[str, CatalogueEntry], path: Path
) -> None:
    """Validate a ``gpu`` profile config against the catalogue (Y3.2, Y3.3, R12 N2).

    Checks per model section: the id exists with the right role, the bare ``model`` is the
    catalogue tag, the family matches, ``options`` equal the catalogue; for the generator also
    ``generation.temperature`` and ``generation.max_tokens`` against ``option_bounds``.

    Raises:
        ConfigError: Any check fails; the message names the id, option and (for bounds) the range.
    """
    for name, part, role in (
        ("generator", cfg.generator, "generator"),
        ("embed", cfg.embed, "embed"),
    ):
        if part.catalogue_id is None:
            continue
        entry = _entry(catalogue, path, part.catalogue_id, role)
        if part.model != entry.tag:
            msg = f"{name}.model {part.model!r} is not the catalogue tag {entry.tag!r}"
            raise ConfigError(msg)
        _check_options(name, part.options, entry)
        if name == "generator":
            _check_generator(cfg, entry)


def _check_generator(cfg: RagConfig, entry: CatalogueEntry) -> None:
    if cfg.generator.family != entry.family:
        msg = (
            f"generator.family {cfg.generator.family!r} is not the catalogue family "
            f"{entry.family!r}"
        )
        raise ConfigError(msg)
    if cfg.generation is not None:
        bounds = entry.option_bounds
        _check_bound("temperature", cfg.generation.temperature, bounds.get("temperature"))
        _check_bound("max_tokens", cfg.generation.max_tokens, bounds.get("num_predict"))

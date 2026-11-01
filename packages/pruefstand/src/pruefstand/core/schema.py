"""JSON Schema export of the persisted models (interfaces: models marked *(schema)*)."""

import json
from pathlib import Path

from pydantic import BaseModel

from pruefstand.core.config import PruefstandConfig
from pruefstand.core.models.attacks import CanaryRegistry
from pruefstand.core.models.corpus import Chunk, CorpusManifest
from pruefstand.core.models.run import RunManifest
from pruefstand.core.models.testcase import TestCase

_REGISTRY: dict[str, type[BaseModel]] = {}


def register_schema(name: str, model: type[BaseModel]) -> None:
    """Register ``model`` to be exported as ``<name>.schema.json``.

    Later tasks add one call each. Registering the same pair twice is a no-op.

    Args:
        name: File stem of the schema.
        model: The Pydantic model.

    Raises:
        ValueError: ``name`` is already registered for a different model.
    """
    if _REGISTRY.setdefault(name, model) is not model:
        msg = f"schema {name!r} is already registered for {_REGISTRY[name].__name__}"
        raise ValueError(msg)


def export_schemas(out: Path) -> list[Path]:
    """Write ``<name>.schema.json`` for every registered model into ``out``.

    Output is deterministic: keys sorted, two-space indent, UTF-8, trailing newline.

    Args:
        out: Target directory (created if missing).

    Returns:
        The written paths, sorted by name.
    """
    out.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for name in sorted(_REGISTRY):
        path = out / f"{name}.schema.json"
        text = json.dumps(
            _REGISTRY[name].model_json_schema(), sort_keys=True, indent=2, ensure_ascii=False
        )
        path.write_text(text + "\n", encoding="utf-8")
        paths.append(path)
    return paths


register_schema("testcase", TestCase)
register_schema("chunk", Chunk)
register_schema("corpus_manifest", CorpusManifest)
register_schema("run_manifest", RunManifest)
register_schema("canary_registry", CanaryRegistry)
register_schema("pruefstand_config", PruefstandConfig)

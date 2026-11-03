"""Loading ``RagConfig``, hashing it, and the typed runtime settings (environment only)."""

import hashlib
import json
from pathlib import Path

import yaml
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from rag_demo.catalogue import check_against_catalogue, load_catalogue
from rag_demo.errors import ConfigError
from rag_demo.models import RagConfig

PACKAGE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """Deployment settings from environment variables; none of them is part of ``config_hash``."""

    model_config = SettingsConfigDict(populate_by_name=True, extra="ignore")

    rag_config: Path = Path("configs/rag.yaml")
    qdrant_url: str = "http://localhost:6333"
    llm_url: str = "http://localhost:8080"
    embed_url: str = "http://localhost:8090"
    collection: str = Field(
        default="slice_v2", validation_alias=AliasChoices("RAG_COLLECTION", "collection")
    )
    git_sha: str = "unknown"
    image_digest: str | None = None
    llama_cpp_version: str = "unknown"
    model_sha256: str = ""
    model_file: str = ""
    model_pin: str = ""
    rag_model_catalogue: Path | None = None
    serving_engine_version: str = "unknown"
    serving_gpu: str = "unknown"


def resolve_model_sha(settings: Settings) -> str:
    """SHA-256 of the served GGUF: ``MODEL_SHA256`` if set, else the pin for the pinned file.

    ``MODEL_PIN`` is ``<file>=<sha256>``. With another ``MODEL_FILE`` (an overridden generator)
    and no explicit hash the answer is ``unknown``, never a hash of a different file.

    Examples:
        >>> resolve_model_sha(Settings(model_file="a.gguf", model_pin="a.gguf=abc"))
        abc
        >>> resolve_model_sha(Settings(model_file="b.gguf", model_pin="a.gguf=abc"))
        unknown
    """
    if settings.model_sha256:
        return settings.model_sha256
    pinned_file, _, pinned_sha = settings.model_pin.partition("=")
    return pinned_sha if pinned_file and pinned_file == settings.model_file else "unknown"


def parse_config(text: str, catalogue_path: Path | None = None) -> RagConfig:
    """Parse YAML text into a validated ``RagConfig``.

    Args:
        text: YAML text of a ``rag*.yaml``.
        catalogue_path: ``models.yaml`` for the ``gpu`` profile (default: env
            ``RAG_MODEL_CATALOGUE``); ignored for the ``live`` profile.

    Raises:
        pydantic.ValidationError: Unknown key, wrong type or value out of range.
        ConfigError: The text is not a YAML mapping, or a ``gpu`` config disagrees with the
            catalogue (unknown id, option mismatch, value outside ``option_bounds``).
    """
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        msg = "config must be a YAML mapping"
        raise ConfigError(msg)
    cfg = RagConfig.model_validate(data)
    if cfg.profile == "gpu":
        path = catalogue_path or Settings().rag_model_catalogue
        if path is None:
            msg = "profile gpu needs the model catalogue: set RAG_MODEL_CATALOGUE"
            raise ConfigError(msg)
        check_against_catalogue(cfg, load_catalogue(path), path)
    return cfg


def load_config(path: Path, catalogue_path: Path | None = None) -> RagConfig:
    """Read and validate a ``rag*.yaml`` file (see ``parse_config``)."""
    return parse_config(path.read_text(encoding="utf-8"), catalogue_path)


def prompt_path(prompt_file: str, root: Path | None = None) -> Path:
    """Resolve ``prompt_file`` below the package prompt directory.

    Raises:
        ConfigError: The path escapes the prompt root or does not exist.
    """
    base = (root or PACKAGE_DIR).resolve()
    path = (base / prompt_file).resolve()
    if base not in path.parents or not path.is_file():
        msg = f"prompt file {prompt_file!r} not found below the prompt root"
        raise ConfigError(msg)
    return path


def config_hash(cfg: RagConfig, prompts_root: Path | None = None) -> str:
    """Return the first 16 hex of sha256 over the canonical config JSON plus the prompt bytes.

    Args:
        cfg: The parsed configuration.
        prompts_root: Directory holding ``prompts/`` (default: the package).

    Returns:
        16 hex characters; changes with any config field and with any byte of the prompt file.
    """
    canonical = json.dumps(cfg.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8"))
    digest.update(b"\0")
    digest.update(prompt_path(cfg.prompt_file, prompts_root).read_bytes())
    return digest.hexdigest()[:16]

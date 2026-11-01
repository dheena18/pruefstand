"""Loading ``RagConfig``, hashing it, and the typed runtime settings (environment only)."""

import hashlib
import json
from pathlib import Path

import yaml
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

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
        default="slice_v1", validation_alias=AliasChoices("RAG_COLLECTION", "collection")
    )
    git_sha: str = "unknown"
    image_digest: str | None = None
    llama_cpp_version: str = "unknown"
    model_sha256: str = "unknown"


def parse_config(text: str) -> RagConfig:
    """Parse YAML text into a validated ``RagConfig``.

    Raises:
        pydantic.ValidationError: Unknown key, wrong type or value out of range.
        ConfigError: The text is not a YAML mapping.
    """
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        msg = "config must be a YAML mapping"
        raise ConfigError(msg)
    return RagConfig.model_validate(data)


def load_config(path: Path) -> RagConfig:
    """Read and validate a ``rag*.yaml`` file (see ``parse_config``)."""
    return parse_config(path.read_text(encoding="utf-8"))


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

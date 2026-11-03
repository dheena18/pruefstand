"""``PruefstandSettings``: environment-driven settings, secrets as ``SecretStr`` (CLAUDE.md §5)."""

import os
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_cache_dir() -> Path:
    home = os.environ.get("PRUEFSTAND_HOME") or "~/pruefstand"
    return Path(home).expanduser() / "cache"


def _default_log_json() -> bool:
    return bool(os.environ.get("CI"))


class PruefstandSettings(BaseSettings):
    """Process settings read from ``PRUEFSTAND_*`` variables (names: ``docs/ops/secrets.md``).

    Attributes:
        github_token: ``GITHUB_TOKEN``; PR publishing only, never model calls (D333).
        gh_models_token: ``PRUEFSTAND_GH_MODELS_TOKEN``; the only GitHub Models credential (D333).
        hf_token: ``HF_TOKEN``, else the alias ``PRUEFSTAND_HF_TOKEN``.
        judge_base_url: ``PRUEFSTAND_JUDGE_BASE_URL``; OpenAI-compatible local judge endpoint.
        log_json: ``PRUEFSTAND_LOG_JSON``; defaults to true when ``CI`` is set.
        cache_dir: ``PRUEFSTAND_CACHE_DIR``; defaults to ``$PRUEFSTAND_HOME/cache``.
        gpu_endpoints_file: ``PRUEFSTAND_GPU_ENDPOINTS``; the endpoint map of ``build_backend``.
        gpu_catalogue_file: ``PRUEFSTAND_GPU_CATALOGUE``; where T5.1 finds the per-model options.
        heldout_dir: ``PRUEFSTAND_HELDOUT_DIR``; held-out canary set (private executor only, T2.6).
    """

    model_config = SettingsConfigDict(
        env_prefix="PRUEFSTAND_",
        frozen=True,
        extra="ignore",
        env_ignore_empty=True,
        populate_by_name=True,
    )

    github_token: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("GITHUB_TOKEN")
    )
    gh_models_token: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("PRUEFSTAND_GH_MODELS_TOKEN")
    )
    hf_token: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("HF_TOKEN", "PRUEFSTAND_HF_TOKEN")
    )
    judge_base_url: str | None = None
    log_json: bool = Field(default_factory=_default_log_json)
    cache_dir: Path = Field(default_factory=_default_cache_dir)
    gpu_endpoints_file: Path = Field(
        default=Path("infra/gpu/endpoints.yaml"),
        validation_alias=AliasChoices("PRUEFSTAND_GPU_ENDPOINTS"),
    )
    gpu_catalogue_file: Path = Field(
        default=Path("infra/gpu/models.yaml"),
        validation_alias=AliasChoices("PRUEFSTAND_GPU_CATALOGUE"),
    )
    heldout_dir: Path | None = Field(
        default=None, validation_alias=AliasChoices("PRUEFSTAND_HELDOUT_DIR")
    )

"""The ``/v1/info`` body: static fields only, from the config and (tier 2) the catalogue (X3.13)."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from rag_demo import __version__
from rag_demo.catalogue import CatalogueEntry
from rag_demo.config import config_hash
from rag_demo.models import RagConfig


def cpu_model(cpuinfo: Path = Path("/proc/cpuinfo")) -> str:
    """The CPU model name of this host ("unknown" if it cannot be read)."""
    try:
        for line in cpuinfo.read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "unknown"


def _gpu_blocks(
    cfg: RagConfig, env: Mapping[str, str], catalogue: Mapping[str, CatalogueEntry]
) -> tuple[dict[str, str], dict[str, str]]:
    gen = catalogue[cfg.generator.catalogue_id or ""]
    rerank = next((e.id for e in catalogue.values() if e.role == "rerank"), "none")
    models = {
        "generator": gen.id,
        "generator_family": gen.family,
        "embed": cfg.embed.catalogue_id or cfg.embed.model,
        "rerank": rerank if cfg.reranker == "on" else "none",
    }
    serving = {
        "engine": gen.engine,
        "engine_version": env.get("SERVING_ENGINE_VERSION", "unknown"),
        "quantization": gen.quantization,
        "gpu": env.get("SERVING_GPU", "unknown"),
        "model_sha256": gen.digest,
    }
    return models, serving


def build_info(
    cfg: RagConfig,
    *,
    corpus_version: str,
    env: Mapping[str, str],
    cpu_model: str,
    catalogue: Mapping[str, CatalogueEntry] | None = None,
) -> dict[str, Any]:
    """The ``/v1/info`` body; ``serving`` holds static fields only (X3.13).

    Args:
        cfg: Active configuration.
        corpus_version: From the collection metadata.
        env: ``GIT_SHA``, ``IMAGE_DIGEST``, ``LLAMA_CPP_VERSION``, ``MODEL_SHA256`` (tier 1) or
            ``SERVING_ENGINE_VERSION``, ``SERVING_GPU`` (tier 2).
        cpu_model: CPU model name; part of the target fingerprint via ``serving.gpu`` in tier 1.
        catalogue: Catalogue entries by id; required for the ``gpu`` profile (ids, family,
            quantization and the manifest digest come from it).
    """
    if cfg.profile == "gpu" and catalogue is not None:
        models, serving = _gpu_blocks(cfg, env, catalogue)
    else:
        models = {
            "generator": cfg.generator.model,
            "generator_family": cfg.generator.family,
            "embed": cfg.embed.model,
            "rerank": "rerank-cpu" if cfg.reranker == "on" else "none",
        }
        serving = {
            "engine": "llama.cpp",
            "engine_version": env.get("LLAMA_CPP_VERSION", "unknown"),
            "quantization": "Q4_K_M",
            "gpu": f"cpu:{cpu_model}",
            "model_sha256": env.get("MODEL_SHA256", "unknown"),
        }
    return {
        "app_version": __version__,
        "git_sha": env.get("GIT_SHA", "unknown"),
        "image_digest": env.get("IMAGE_DIGEST") or None,
        "config_hash": config_hash(cfg),
        "corpus_version": corpus_version,
        "models": models,
        "serving": serving,
    }

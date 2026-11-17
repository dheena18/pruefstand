"""``plan``: models, index mode and cache mode of one job (S1; X3.15, D9-12, D221, AI12-08).

Only the PR's tier-2 profile ``apps/rag-demo/configs/rag.gpu.yaml`` is read, as data (``rag.yaml``
is the tier-1 CPU profile and never read here). Its generator and embedding ``catalogue_id`` must
be ``ollama/<tag>`` entries of ``infra/gpu/models.yaml`` with the matching role; anything else
gives ``status_hint="unsupported_config"`` (WARN, gate not run) and main's models. An embedding
change against main's profile (model, prefixes, input length, dimension) needs a PR-scoped index
``pr_<N>_<shortsha>``. PR jobs use the cache overlay; main, nightly and release the shared cache.
"""

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict

from gate_orchestrator.models import Job

EMBED_INDEX_KEYS = ("catalogue_id", "query_prefix", "doc_prefix", "max_input_tokens", "dim")


class JobPlan(BaseModel):
    """What one job serves and how it indexes (prompt T6.2a "Interfaces")."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    job: Job
    generator: str
    embedder: str
    index_mode: Literal["shared", "pr_scoped"]
    cache_mode: Literal["shared", "overlay"]
    status_hint: Literal["ok", "unsupported_config"]


def _section(cfg: Mapping[str, object], name: str) -> Mapping[str, object]:
    value = cfg.get(name)
    return value if isinstance(value, Mapping) else {}


def _roles(catalogue: Mapping[str, object]) -> dict[str, str]:
    models = catalogue.get("models")
    if not isinstance(models, list):
        return {}
    return {
        str(m.get("id")): str(m.get("role"))
        for m in models
        if isinstance(m, Mapping) and m.get("engine") == "ollama"
    }


def _model(
    cfg: Mapping[str, object], section: str, role: str, roles: Mapping[str, str]
) -> str | None:
    model_id = _section(cfg, section).get("catalogue_id")
    if isinstance(model_id, str) and roles.get(model_id) == role:
        return model_id
    return None


def plan(
    job: Job,
    rag_yaml: Mapping[str, object],
    catalogue: Mapping[str, object],
    *,
    main_rag_yaml: Mapping[str, object],
) -> JobPlan:
    """Build the job plan.

    Args:
        job: the selected job.
        rag_yaml: the parsed ``rag.gpu.yaml`` of the job's SHA (data only).
        catalogue: the parsed trusted ``infra/gpu/models.yaml``.
        main_rag_yaml: the parsed ``rag.gpu.yaml`` of trusted ``main`` (the reference).

    Returns:
        :class:`JobPlan`.

    Raises:
        ValueError: main's own profile names models outside the catalogue.
    """
    roles = _roles(catalogue)
    main_gen = _model(main_rag_yaml, "generator", "generator", roles)
    main_emb = _model(main_rag_yaml, "embed", "embed", roles)
    if main_gen is None or main_emb is None:
        msg = "main's rag.gpu.yaml names a model outside infra/gpu/models.yaml"
        raise ValueError(msg)
    gen = _model(rag_yaml, "generator", "generator", roles)
    emb = _model(rag_yaml, "embed", "embed", roles)
    cache: Literal["shared", "overlay"] = "overlay" if job.tier == "pr" else "shared"
    if gen is None or emb is None:
        return JobPlan(
            job=job,
            generator=main_gen,
            embedder=main_emb,
            index_mode="shared",
            cache_mode=cache,
            status_hint="unsupported_config",
        )
    pr_embed, main_embed = _section(rag_yaml, "embed"), _section(main_rag_yaml, "embed")
    changed = any(pr_embed.get(k) != main_embed.get(k) for k in EMBED_INDEX_KEYS)
    return JobPlan(
        job=job,
        generator=gen,
        embedder=emb,
        index_mode="pr_scoped" if changed else "shared",
        cache_mode=cache,
        status_hint="ok",
    )


def collection_name(pr_number: int, sha: str) -> str:
    """PR-scoped Qdrant collection ``pr_<N>_<shortsha>`` (7 hex chars).

    >>> collection_name(42, "1a2b3c4d" + "0" * 32)
    'pr_42_1a2b3c4'
    """
    return f"pr_{pr_number}_{sha[:7]}"

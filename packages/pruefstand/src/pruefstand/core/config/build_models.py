"""Models, generation, perturbation and review settings of ``dataset.yaml`` (T4.7a).

``DatasetBuildConfig`` (``build.py``) embeds these. They hold only model ids, counts and paths; the
rules (family separation, public-text datagen) are checked here and again by the code that builds
the clients (``dataset.datagen_guard``, ``llm.policy``).
"""

from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pruefstand.core.config.run import ModelRef

DETERMINISTIC_PERTURBATIONS = ("umlaut_translit", "eszett", "numbers", "dates", "citation_style")
"""The deterministic perturbations ``dataset.yaml`` applies by default (the others need a model)."""
_Count = Annotated[int, Field(ge=0, le=100_000)]


class BuildModels(BaseModel):
    """The models of a build, each with its family (ADR-0009, ADR-0019).

    Attributes:
        datagen: Writes the questions (GitHub Models, public text only).
        generator: The generator of the system under test (``qwen``); only its family matters:
            no reviewer or support model may share it.
        support: Judges whether a generated answer is supported by its chunk (T4.3); another
            family than ``datagen``.
        rewriter: Writes the LLM-assisted perturbations (T4.5); ``None`` = deterministic only.
        perturb_validator: Checks that a rewrite keeps the meaning; another family than
            ``rewriter``. Needed as soon as ``rewriter`` is set.
        rewrite_local: A local model that rewrites the questions of private tenants (the external
            rewriter never sees them); None = LLM-assisted variants for public text only.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    datagen: ModelRef
    generator: ModelRef
    support: ModelRef | None = None
    rewriter: ModelRef | None = None
    perturb_validator: ModelRef | None = None
    rewrite_local: ModelRef | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.support is not None and self.support.family == self.datagen.family:
            msg = f"support model family '{self.support.family}' equals the datagen family"
            raise ValueError(msg)
        if self.rewriter is not None:
            if self.perturb_validator is None:
                msg = "models.rewriter needs models.perturb_validator"
                raise ValueError(msg)
            if self.perturb_validator.family == self.rewriter.family:
                msg = "models.perturb_validator must be of another family than models.rewriter"
                raise ValueError(msg)
        return self


class EmbedConfig(BaseModel):
    """The embedding server of the near-duplicate filter (T4.3); the URL is a local service."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str = Field(min_length=1)
    api: Literal["tei", "ollama"] = "tei"
    model: str = "bge-m3"


class GenerationConfig(BaseModel):
    """What the ``generate`` stage asks the datagen model for.

    Attributes:
        units: ``{category: units per tenant}``, category one of ``factual``, ``comparison``,
            ``multi_hop``, ``cross_lingual``; a unit is a chunk or a chunk pair.
        prompt_versions: Overrides of the pinned prompt per category (``qa_factual_de_v1``).
        exclude_file: JSON list of document ids never sampled (the in-domain dev set), or None.
        citation_graph: Directory of the OLDP citation graph for multi-hop pairs, or None.
        candidates_from: A ``candidates.jsonl`` of ``scripts/generate_qa.py``; the stage then copies
            it and makes no datagen call (the quota-limited run of T4.2 is done separately).
        concurrency: Requests in flight.
        max_requests: Cap on charged datagen requests of one run (None = no cap).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    units: dict[str, _Count] = Field(default_factory=dict, max_length=8)
    prompt_versions: dict[str, str] = Field(default_factory=dict, max_length=8)
    exclude_file: Path | None = None
    citation_graph: Path | None = None
    candidates_from: Path | None = None
    concurrency: int = Field(default=4, ge=1, le=32)
    max_requests: int | None = Field(default=None, ge=1)


class PerturbConfig(BaseModel):
    """What the ``perturb`` stage applies (SPEC §4.1).

    Attributes:
        deterministic: Names of the deterministic perturbations applied to every answerable base.
        llm: Names of the LLM-assisted perturbations (need ``models.rewriter``).
        llm_bases: How many top-ranked bases (by applicability) get the LLM-assisted variants.
        seed: Seed of the per-item randomness.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    deterministic: tuple[str, ...] = DETERMINISTIC_PERTURBATIONS
    llm: tuple[str, ...] = ()
    llm_bases: _Count = 0
    seed: int = Field(default=0, ge=0)


class ReviewersConfig(BaseModel):
    """The reviewer per split group (round 9 X3.8, ADR-0019): both name the one judge model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    core_smoke: ModelRef
    full: ModelRef


class ReviewConfig(BaseModel):
    """Model review and owner spot-check settings (SPEC §3.5 steps 4-5, W3.13).

    Attributes:
        reviewers: The reviewer models.
        prompt_version: The review prompt (``review_item_de_v1``).
        full_fraction: Share of ``full`` sampled per (category x prompt version) stratum.
        min_per_category: Smallest number of ``full`` cases reviewed per category.
        error_threshold: A stratum above this error rate needs regeneration.
        spotcheck_size: Items of the owner spot-check (all smoke items first).
        spotcheck_max_flag_rate: Share of model-``ok`` items the owner may flag before the model
            review is not trusted.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    reviewers: ReviewersConfig
    prompt_version: str = "review_item_de_v1"
    full_fraction: float = Field(default=0.2, gt=0.0, le=1.0)
    min_per_category: _Count = 30
    error_threshold: float = Field(default=0.10, ge=0.0, le=1.0)
    spotcheck_size: _Count = 50
    spotcheck_max_flag_rate: float = Field(default=0.10, ge=0.0, le=1.0)

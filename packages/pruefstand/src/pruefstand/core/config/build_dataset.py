"""``DatasetBuildConfig``: the inputs of ``pruefstand build-dataset`` (interfaces §14, T4.1, T4.7a).

``dataset.yaml`` is a ``DatasetBuildConfig``. T4.1 defined the first seven fields; T4.7a adds the
optional blocks for models, generation, filters, perturbations and review (additive, defaults keep
every T4.1 call valid). Relative paths are resolved against the directory of the config file by
the CLI.
"""

from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pruefstand.core.config.build import Short, SplitPlan
from pruefstand.core.config.build_models import (
    BuildModels,
    EmbedConfig,
    GenerationConfig,
    PerturbConfig,
    ReviewConfig,
)
from pruefstand.core.models.dataset import FilterConfig

_LOCAL_PROVIDERS = frozenset({"ollama", "openai_compatible_local"})


class DatasetBuildConfig(BaseModel):
    """Inputs of ``build_dataset`` (interfaces §15): which corpus, which plan, which seed.

    Attributes:
        version: Schema version of this file.
        name: Dataset name (``datasets/<name>/<dataset_version>/``).
        dataset_version: Dataset version, e.g. ``"v1"``.
        corpus_dir: The corpus the questions are generated from (T2.5 output).
        out_dir: Root under which the dataset directory is written.
        split_plan: Sizes and quotas.
        seed: Seed of ``assign_splits`` (recorded as ``assignment_seed``).
        prompt_versions: Versioned prompt files used per step (recorded in the manifest).
        corpus_config: ``corpus.yaml`` of the corpus (its ``attacks`` block makes the injection
            cases); None = no injection cases.
        models: The models of the build; None = a run that only reuses earlier stage outputs.
        generation: The ``generate`` stage settings.
        filters: Thresholds of the QA filters.
        embed: Embedding server of the near-duplicate filter.
        perturb: The ``perturb`` stage settings.
        review: Model review settings; None = no model review configured.
        work_dir: Where ``stage_<n>_<name>.jsonl`` files go (git-ignored).
        check_refusal_laws: Check that every refusal template names a law of the tenant corpus (a
            small slice corpus lacks most laws: switch this off there).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1] = 1
    name: Short
    dataset_version: Short
    corpus_dir: Path
    out_dir: Path = Path("datasets")
    split_plan: SplitPlan = Field(default_factory=SplitPlan)
    seed: int = Field(default=0, ge=0)
    prompt_versions: dict[Short, Short] = Field(default_factory=dict, max_length=64)
    corpus_config: Path | None = None
    models: BuildModels | None = None
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    filters: FilterConfig = Field(default_factory=FilterConfig)
    embed: EmbedConfig | None = None
    perturb: PerturbConfig = Field(default_factory=PerturbConfig)
    review: ReviewConfig | None = None
    work_dir: Path = Path("datasets/_work")
    check_refusal_laws: bool = True

    @model_validator(mode="after")
    def _family_separation(self) -> Self:
        """Reviewers differ in family from the datagen model and the generator (X3.8, ADR-0019)."""
        if self.review is None:
            return self
        if self.models is None:
            msg = "review needs models (the reviewer families are checked against them)"
            raise ValueError(msg)
        taken = {"datagen": self.models.datagen.family, "generator": self.models.generator.family}
        for slot in ("core_smoke", "full"):
            ref = getattr(self.review.reviewers, slot)
            if ref.id.split("/", 1)[0] not in _LOCAL_PROVIDERS:
                msg = f"review.reviewers.{slot} must be a local model"
                raise ValueError(msg)
            family = ref.family
            for role, other in taken.items():
                if family == other:
                    msg = f"review.reviewers.{slot} family '{family}' equals the {role} family"
                    raise ValueError(msg)
        return self

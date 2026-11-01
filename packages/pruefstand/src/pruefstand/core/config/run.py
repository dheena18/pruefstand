"""Run-level configs and the root ``PruefstandConfig`` (interfaces §8, §15)."""

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pruefstand.core.config.gate import JUDGED_METRICS, GatePolicy
from pruefstand.core.config.target import TargetConfig
from pruefstand.core.enums import Split
from pruefstand.core.errors import ConfigError
from pruefstand.core.models_family import UNKNOWN, known_families, model_family

_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_FAMILY_HINT = "add it to core/data/model_families.yaml"


class ModelRef(BaseModel):
    """A model id with an explicit family (ADR-0009)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    family: str = Field(min_length=1)


class JudgeConfig(BaseModel):
    """Judge models: PR, nightly and optional per-metric overrides (every one with its family)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pr: ModelRef
    nightly: ModelRef
    per_metric: dict[str, ModelRef] = {}


class BudgetConfig(BaseModel):
    """Per-run limits; free providers only, so the USD cap defaults to 0.

    ``max_requests_per_run`` is the tier-1 judge cap (D143), counted in LLM calls.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_usd_per_run: float | None = Field(default=0.0, ge=0, allow_inf_nan=False)
    max_tokens_per_run: int | None = Field(default=None, ge=0)
    max_requests_per_run: int | None = Field(default=None, ge=0)


class RunnerConfig(BaseModel):
    """Runner settings (interfaces §8); there is deliberately no judge field (D143)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    concurrency: int = Field(default=8, ge=1)
    timeout_s: float = Field(default=60, gt=0, allow_inf_nan=False)
    max_retries: int = Field(default=3, ge=0)
    backoff_s: float = Field(default=1.0, ge=0, allow_inf_nan=False)


class LLMPolicyConfig(BaseModel):
    """Which providers may be used; free-only by default (provider names are checked by T1.4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed_providers: tuple[str, ...] = ("openai_compatible_local", "ollama", "github")
    allow_paid: bool = False
    fallback_judge: ModelRef | None = None


class BaselineStoreConfig(BaseModel):
    """Where baselines live.

    Raises:
        ConfigError: ``local_dir`` without ``path``, ``git_branch`` without ``repo``, or a
            ``repo`` that is not ``owner/name``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["local_dir", "git_branch"] = "git_branch"
    path: Path | None = None
    repo: str | None = None
    branch: str = Field(default="baselines", min_length=1)
    data_root: Path | None = None

    @model_validator(mode="after")
    def _check_store(self) -> Self:
        if self.type == "local_dir" and self.path is None:
            msg = "baseline_store: type 'local_dir' needs 'path'"
            raise ConfigError(msg)
        if self.type == "git_branch":
            if not self.repo:
                msg = "baseline_store: type 'git_branch' needs 'repo' (owner/name)"
                raise ConfigError(msg)
            if _REPO.fullmatch(self.repo) is None:
                msg = f"baseline_store.repo: {self.repo!r} is not 'owner/name'"
                raise ConfigError(msg)
        return self


class PruefstandConfig(BaseModel):
    """The root of ``pruefstand.yaml`` (interfaces §15).

    Raises:
        ConfigError: a judge family equals ``generator_family`` (ADR-0009), a family is unknown
            or contradicts the model id, or a ``per_metric`` key is not a known metric.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1]
    target: TargetConfig
    dataset: str = Field(min_length=1)
    splits: tuple[Split, ...] = Field(min_length=1)
    judge: JudgeConfig
    gate: GatePolicy
    budget: BudgetConfig
    runner: RunnerConfig
    llm: LLMPolicyConfig = LLMPolicyConfig()
    generator_family: str = Field(min_length=1)
    baseline_store: BaselineStoreConfig
    seed: int = 1234

    def _judge_refs(self) -> Iterator[tuple[str, ModelRef]]:
        yield "judge.pr", self.judge.pr
        yield "judge.nightly", self.judge.nightly
        for metric, ref in self.judge.per_metric.items():
            yield f"judge.per_metric.{metric}", ref
        if self.llm.fallback_judge is not None:
            yield "llm.fallback_judge", self.llm.fallback_judge

    @model_validator(mode="after")
    def _check_families(self) -> Self:
        known = known_families()
        if self.generator_family not in known:
            msg = f"generator_family: unknown family {self.generator_family!r}; {_FAMILY_HINT}"
            raise ConfigError(msg)
        for metric in self.judge.per_metric:
            if metric not in JUDGED_METRICS:
                msg = f"judge.per_metric.{metric}: not a judged metric ({sorted(JUDGED_METRICS)})"
                raise ConfigError(msg)
        for path, ref in self._judge_refs():
            if ref.family not in known:
                msg = f"{path}: unknown family {ref.family!r}; {_FAMILY_HINT}"
                raise ConfigError(msg)
            inferred = model_family(ref.id)
            if inferred not in (UNKNOWN, ref.family):
                msg = f"{path}: id looks like {inferred!r} but family says {ref.family!r}"
                raise ConfigError(msg)
            if ref.family == self.generator_family:
                msg = (
                    f"{path}: family {ref.family!r} equals generator_family "
                    f"{self.generator_family!r} (ADR-0009)"
                )
                raise ConfigError(msg)
        return self

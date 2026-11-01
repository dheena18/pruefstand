"""Gate input and result models (interfaces §9): ``ScoreTable`` and ``BootstrapResult``.

The other gate models (``SliceDecision``, ``HardFailFinding``, ``GateReport``, ``CauseCode``) are
added by T1.7.
"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pruefstand.core.ids import CaseId


class ScoreTable(BaseModel):
    """One metric of one run, one value per case, aligned by ``case_id`` when paired.

    ``slices`` maps a dimension (``category``, ``perturbation``, ``tenant``, ``lang``, ``tags``)
    to the slice value of each case.

    Raises:
        ValidationError: ``case_ids``, ``cluster_ids``, ``values`` and every ``slices`` value
            tuple do not all have the same length.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric: str
    higher_is_better: bool
    case_ids: tuple[CaseId, ...]
    cluster_ids: tuple[str, ...]
    values: tuple[float, ...]
    slices: dict[str, tuple[str, ...]]

    @model_validator(mode="after")
    def _aligned(self) -> Self:
        n = len(self.case_ids)
        if len(self.cluster_ids) != n or len(self.values) != n:
            msg = "case_ids, cluster_ids and values must have the same length"
            raise ValueError(msg)
        for name, column in self.slices.items():
            if len(column) != n:
                msg = f"slice {name!r} has {len(column)} values for {n} cases"
                raise ValueError(msg)
        return self


class BootstrapResult(BaseModel):
    """Result of a paired cluster bootstrap (negative ``mean_diff`` = candidate worse).

    ``p_value`` is one-sided for H0 "no drop" (mean difference >= 0). ``ci_low``/``ci_high`` are the
    display interval at ``confidence``; ``method`` says where ``p_value`` came from.

    Raises:
        ValidationError: A float is not finite, ``p_value`` is outside [0, 1],
            ``n_clusters`` exceeds ``n_cases`` or a count is below 1.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    mean_diff: float
    ci_low: float
    ci_high: float
    p_value: float = Field(ge=0.0, le=1.0)
    method: Literal["bootstrap", "sign_test"]
    se: float = Field(ge=0.0)
    n_cases: int = Field(ge=1)
    n_clusters: int = Field(ge=1)
    n_resamples: int = Field(ge=1)
    confidence: float = Field(gt=0.0, lt=1.0)

    @model_validator(mode="after")
    def _clusters_le_cases(self) -> Self:
        if self.n_clusters > self.n_cases:
            msg = "n_clusters cannot exceed n_cases"
            raise ValueError(msg)
        return self

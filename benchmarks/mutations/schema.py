"""``MutationSpec`` and the ``index.yaml`` loader of the RQ3 mutation benchmark (T7.1a S1).

``MutationSpec`` is local to ``benchmarks/`` (not a cross-module contract). The rules a single
entry can check on its own (tier and splits agree, the P3.3 ``FAIL`` rule for ``statistical``
entries, the normaliser stratum, exactly one of ``patch`` / ``rag_overrides``) are validators here;
the rules that need the shipped gate policy or the metric registry (the X3.10 pre-registration
check) live in ``benchmarks/tests/test_mutations.py``.
"""

from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from pruefstand.core.errors import ConfigError
from pruefstand.core.models.gate import CauseCode

MUTATIONS_ROOT = Path(__file__).resolve().parent
GatedSlice = Literal["overall", "tenant", "lang", "perturbed_all"]
SplitName = Literal["smoke", "core", "robust_pr", "full"]
PR_SPLITS: frozenset[str] = frozenset({"smoke", "core", "robust_pr"})
LEAK_METRICS: frozenset[str] = frozenset({"canary_leak", "tenant_leak"})


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Expected(_Frozen):
    """Machine-readable expected effect of one entry (SPEC §8 RQ3)."""

    status: Literal["FAIL", "WARN", "PASS"]
    hard_fail: bool = False
    metrics: tuple[str, ...] = ()
    secondary_metrics: tuple[str, ...] = ()
    gated_slices: tuple[GatedSlice, ...] = ()
    informational_slices: tuple[str, ...] = ()
    likely_cause: CauseCode | None = None


class MutationSpec(_Frozen):
    """One mutation (``M<nn>``) or no-op (``N<nn>``) entry, read from ``<ID>/mutation.yaml``.

    Raises:
        ValidationError: an entry-local rule is broken (see the module docstring).
    """

    id: str = Field(pattern=r"^[MN]\d{2}$")
    title: str
    kind: Literal["config", "code", "data"]
    patch: str | None = None
    rag_overrides: dict[str, JsonValue] | None = None
    needs_reindex: bool
    cache_invalidating: bool
    tier: Literal["pr", "nightly"]
    splits: tuple[SplitName, ...] = Field(min_length=1)
    stratum: Literal["deterministic", "statistical", "normaliser"]
    tier1: bool
    in_detection_rate: bool
    expected: Expected
    rationale: str = Field(min_length=20)
    silent: bool = False
    silent_reason: str | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        problems = [*_shape_problems(self), *_tier_problems(self)]
        if problems:
            raise ValueError(f"{self.id}: " + "; ".join(problems))
        return self

    @property
    def is_leak(self) -> bool:
        """True for a leak mutation (expected hard fail on ``tenant_leak`` / ``canary_leak``)."""
        return self.expected.hard_fail and bool(LEAK_METRICS & set(self.expected.metrics))


def _shape_problems(spec: MutationSpec) -> list[str]:
    problems = []
    if (spec.patch is None) == (spec.rag_overrides is None):
        problems.append("exactly one of patch and rag_overrides")
    if spec.kind == "config" and spec.rag_overrides is None:
        problems.append("kind config needs rag_overrides")
    if spec.silent and not spec.silent_reason:
        problems.append("silent needs silent_reason")
    is_noop = spec.id.startswith("N")
    if is_noop and (spec.expected.status != "PASS" or spec.expected.hard_fail):
        problems.append("a no-op expects PASS without a hard fail")
    return problems


def _tier_problems(spec: MutationSpec) -> list[str]:
    problems = []
    if spec.tier == "nightly" and spec.splits != ("full",):
        problems.append("tier nightly runs on splits [full] only (X3.10, D223)")
    if spec.tier == "pr" and not set(spec.splits) <= PR_SPLITS:
        problems.append("tier pr runs on smoke/core/robust_pr only")
    if spec.stratum == "statistical" and spec.expected.status != "FAIL":
        problems.append("a statistical entry expects FAIL (round 13 P3.3)")
    if (spec.stratum == "normaliser") == spec.in_detection_rate:
        problems.append("in_detection_rate is false exactly for the normaliser stratum")
    if spec.tier1 and not spec.expected.hard_fail:
        problems.append("tier1 only for hard-fail entries (X5.6)")
    return problems


class MutationIndex(_Frozen):
    """``index.yaml``: the commit every patch applies to and the entry list."""

    base_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    entries: tuple[str, ...] = Field(min_length=1)


def load_index(root: Path = MUTATIONS_ROOT) -> MutationIndex:
    """Read ``index.yaml``.

    Args:
        root: the ``benchmarks/mutations`` directory.

    Returns:
        The validated index.

    Raises:
        ConfigError: the file is missing or not a mapping.
        ValidationError: the content does not match ``MutationIndex``.
    """
    return MutationIndex.model_validate(_read_mapping(root / "index.yaml"))


def load_spec(entry_id: str, root: Path = MUTATIONS_ROOT) -> MutationSpec:
    """Read and validate ``<root>/<entry_id>/mutation.yaml``.

    Raises:
        ConfigError: the file is missing, not a mapping, or its ``id`` differs from the folder.
        ValidationError: the content does not match ``MutationSpec``.
    """
    spec = MutationSpec.model_validate(_read_mapping(root / entry_id / "mutation.yaml"))
    if spec.id != entry_id:
        msg = f"{entry_id}/mutation.yaml has id {spec.id}"
        raise ConfigError(msg)
    return spec


def load_all(root: Path = MUTATIONS_ROOT) -> list[MutationSpec]:
    """Return every entry listed in ``index.yaml``, in index order."""
    return [load_spec(entry, root) for entry in load_index(root).entries]


def _read_mapping(path: Path) -> dict[str, object]:
    if not path.is_file():
        msg = f"missing file {path}"
        raise ConfigError(msg)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        msg = f"{path} is not a mapping"
        raise ConfigError(msg)
    return data

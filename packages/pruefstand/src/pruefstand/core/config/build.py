"""Build configs: ``TenantPlan`` and ``CorpusBuildConfig`` (T2.5); T4.1 adds the dataset configs.

``corpus.yaml`` is a ``CorpusBuildConfig``. The tenant rules live there, not in code (SPEC §3.1).
A tenant id becomes a file name (``<tenant>.chunks.jsonl``) and a Qdrant filter value, so it is
restricted to a short, safe alphabet before it is used anywhere.
"""

import re
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from pruefstand.core.config.attacks import AttacksConfig
from pruefstand.core.config.private_docs import PrivateDocsConfig
from pruefstand.core.ids import TenantId

TENANT_ID_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,62}")
UNASSIGNED_TENANT = "unassigned"  # what the loaders emit; never a valid tenant of a plan
_MAX_METADATA_KEYS = 8
_MAX_TEXT = 200


def validate_tenant_id(value: str) -> TenantId:
    """Return ``value`` as a ``TenantId`` if it is a safe tenant name.

    Args:
        value: Candidate: 1 to 63 characters of ``a-z``, ``0-9`` and ``_``, starting with a
            letter, and not the reserved name ``unassigned``.

    Returns:
        The same string typed as ``TenantId``.

    Raises:
        ValueError: ``value`` is not a safe tenant id (the message starts with "tenant id").

    Examples:
        >>> validate_tenant_id("kanzlei_mueller")
        'kanzlei_mueller'
        >>> validate_tenant_id("../etc")
        Traceback (most recent call last):
        ...
        ValueError: tenant id '../etc' must match [a-z][a-z0-9_]{0,62} and not be 'unassigned'
    """
    if not TENANT_ID_PATTERN.fullmatch(value) or value == UNASSIGNED_TENANT:
        shown = value if len(value) <= 24 else value[:24] + "..."
        msg = (
            f"tenant id {shown!r} must match {TENANT_ID_PATTERN.pattern} "
            f"and not be {UNASSIGNED_TENANT!r}"
        )
        raise ValueError(msg)
    return TenantId(value)


TenantName = Annotated[TenantId, AfterValidator(validate_tenant_id)]
Short = Annotated[str, Field(min_length=1, max_length=_MAX_TEXT)]


class TenantRule(BaseModel):
    """One rule of a tenant plan: a document matching **all** given criteria belongs to ``tenant``.

    Attributes:
        tenant: The tenant that owns matching documents.
        source: Exact ``Document.source`` (``"gii:kschg"``, ``"eurlex:32016R0679"``).
        law_abbrev: Exact ``Document.law_abbrev``.
        metadata: Exact ``Document.metadata`` entries (``{"jurisdiction": "Arbeitsgericht"}``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant: TenantName
    source: Short | None = None
    law_abbrev: Short | None = None
    metadata: dict[Short, Short] = Field(default_factory=dict, max_length=_MAX_METADATA_KEYS)

    @model_validator(mode="after")
    def _has_a_criterion(self) -> Self:
        if self.source is None and self.law_abbrev is None and not self.metadata:
            msg = "a rule needs at least one of source, law_abbrev, metadata (use default_tenant)"
            raise ValueError(msg)
        return self


class TenantPlan(BaseModel):
    """Which documents belong to which tenant (SPEC §3.1).

    Every document goes to exactly one tenant: the one rule it matches, or ``default_tenant`` when
    it matches none (without a default that is an error). Rules must be disjoint.

    Attributes:
        tenants: The tenant ids of the corpus; every one must receive chunks.
        rules: The assignment rules.
        default_tenant: Tenant for documents that match no rule; ``None`` makes them an error.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenants: tuple[TenantName, ...] = Field(min_length=1, max_length=64)
    rules: tuple[TenantRule, ...] = Field(default=(), max_length=1000)
    default_tenant: TenantName | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        declared = set(self.tenants)
        if len(declared) != len(self.tenants):
            msg = "tenants must be unique"
            raise ValueError(msg)
        unknown = {r.tenant for r in self.rules if r.tenant not in declared}
        if self.default_tenant is not None and self.default_tenant not in declared:
            unknown.add(self.default_tenant)
        if unknown:
            msg = f"tenants not declared in tenants: {sorted(unknown)}"
            raise ValueError(msg)
        if len({r.model_dump_json() for r in self.rules}) != len(self.rules):
            msg = "two rules are identical"
            raise ValueError(msg)
        return self

    def sources(self, kind: str) -> tuple[str, ...]:
        """Return the sorted rule sources that start with ``"<kind>:"``.

        Args:
            kind: ``"gii"`` or ``"eurlex"``.

        Returns:
            E.g. ``("gii:arbzg", "gii:kschg")``.
        """
        prefix = f"{kind}:"
        return tuple(
            sorted({r.source for r in self.rules if r.source and r.source.startswith(prefix)})
        )


class CorpusBuildConfig(BaseModel):
    """``corpus.yaml``: the inputs of ``pruefstand ingest``.

    Relative paths are resolved against the directory of the config file.

    Attributes:
        version: Schema version of this file.
        raw_root: Where ``make data`` put the sources (``gii/``, ``eurlex/``, ``hf/``).
        sources_file: ``data/sources.yaml``; its pins go into the corpus manifest.
        loaders: Which sources to load.
        plan: The tenant plan.
        max_tokens: Chunk size in approximate tokens.
        max_chunks: Upper bound on the chunks of one corpus (the build holds them in memory).
        max_problems: How many counted loader problems are tolerated (default none).
        private_docs: Approved synthetic private documents and their canaries (T2.6), or None.
        attacks: Injection documents for the customer tenants (T4.6), or None.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1] = 1
    raw_root: Path = Path("data/raw")
    sources_file: Path = Path("data/sources.yaml")
    loaders: tuple[Literal["gii", "eurlex", "oldp"], ...] = Field(
        default=("gii", "eurlex", "oldp"), min_length=1, max_length=3
    )
    plan: TenantPlan
    max_tokens: int = Field(default=512, ge=128, le=8192)
    max_chunks: int = Field(default=2_000_000, ge=1)
    max_problems: int = Field(default=0, ge=0)
    private_docs: PrivateDocsConfig | None = None
    attacks: AttacksConfig | None = None

    @model_validator(mode="after")
    def _loaders_unique(self) -> Self:
        if len(set(self.loaders)) != len(self.loaders):
            msg = "loaders must be unique"
            raise ValueError(msg)
        return self


PERTURBATION_TYPES = (
    "compound_split",
    "umlaut_translit",
    "eszett",
    "register",
    "gender",
    "numbers",
    "dates",
    "citation_style",
    "abbreviations",
    "typos",
    "colloquial",
)
"""The eleven perturbation names of SPEC §4.1 (``robust_pr`` needs bases for each)."""
NUM_BLOCKS = 3
"""Nightly blocks of ``full`` (round 13 P3.1)."""
_Size = Annotated[int, Field(ge=0, le=100_000)]


class SplitPlan(BaseModel):
    """Sizes and quotas of the dataset splits (interfaces §2 ``Split``, §14; T4.1).

    The defaults are the table of SPEC §3.4 with the round 13 ``full`` quota (P3.1) and the
    ``rq1`` size (P3.2). A size of 0 switches the split (or part) off, which tests use to
    exercise one split at a time; ``validate_dataset`` always checks against the *defaults*.

    Attributes:
        smoke_size: Cases of ``smoke``; ``smoke_min_per_category`` per category present.
        core_answerable: Answerable ``core`` cases (factual, multi_hop, comparison,
            cross_lingual) with at least ``core_min_cross_lingual`` cross-lingual ones.
        core_unanswerable: ``unanswerable`` ``core`` cases.
        core_injection: ``injection`` ``core`` cases (the security probes of the Wilson check).
        core_min_answerable_clusters: Distinct clusters among the answerable ``core`` cases.
        min_clusters_per_tenant: Clusters per tenant in answerable ``core`` and in a ``full`` block.
        judged_subset_size: ``core`` cases flagged ``judged_subset``.
        robust_pr_bases: Bases of ``robust_pr`` (one per cluster); at least
            ``robust_pr_min_bases_per_type`` of them per type in ``robust_pr_types`` and at least
            ``robust_pr_min_perturbed`` perturbed cases in total.
        full_refusal: ``unanswerable`` cases of the ``full`` refusal stratum, within
            ``full_refusal_min`` .. ``full_refusal_max`` and on ``full_refusal_min_clusters``.
        full_block_unperturbed: Unperturbed answerable cases per nightly block (at least
            ``full_block_min_clusters`` clusters); ``full_block_perturbed`` is the most perturbed
            variants of one block.
        nightly_cap: Most cases of refusal stratum plus one block (SPEC §6.2).
        rq1_bases: Bases of ``rq1`` (one per cluster).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    smoke_size: _Size = 50
    smoke_min_per_category: _Size = 3
    core_answerable: _Size = 220
    core_unanswerable: _Size = 50
    core_injection: _Size = 30
    core_min_cross_lingual: _Size = 30
    core_min_answerable_clusters: _Size = 200
    min_clusters_per_tenant: _Size = 30
    judged_subset_size: _Size = 150
    robust_pr_bases: _Size = 40
    robust_pr_min_bases_per_type: _Size = 20
    robust_pr_min_perturbed: _Size = 300
    robust_pr_types: tuple[Short, ...] = PERTURBATION_TYPES
    full_refusal: _Size = 150
    full_refusal_min: _Size = 135
    full_refusal_max: _Size = 165
    full_refusal_min_clusters: _Size = 100
    full_block_unperturbed: _Size = 300
    full_block_perturbed: _Size = 150
    full_block_min_clusters: _Size = 250
    nightly_cap: _Size = 600
    rq1_bases: _Size = 300

    @property
    def core_size(self) -> int:
        """Total ``core`` cases."""
        return self.core_answerable + self.core_unanswerable + self.core_injection

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.judged_subset_size > self.core_size:
            msg = "judged_subset_size must not exceed the core size"
            raise ValueError(msg)
        if (
            self.full_refusal
            and not self.full_refusal_min <= self.full_refusal <= self.full_refusal_max
        ):
            msg = "full_refusal must lie within full_refusal_min..full_refusal_max"
            raise ValueError(msg)
        return self


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

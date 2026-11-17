"""Orchestrator-local models (prompt T6.2a "Interfaces"; not a cross-module contract)."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

Tier = Literal["pr", "main", "nightly", "release"]
SHA_PATTERN = r"^[0-9a-f]{40}$"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Dispatch(_Frozen):
    """The ``workflow_dispatch`` of ``gate-executor.yml`` (round 13 P1.2): PR, actor, run id."""

    pr: int = Field(gt=0)
    actor: str = Field(min_length=1)
    dispatch_run_id: int = Field(gt=0)


class Job(_Frozen):
    """One unit of executor work: a ``gate`` run or a ``pending`` status (P4.2)."""

    kind: Literal["gate", "pending"]
    sha: str = Field(pattern=SHA_PATTERN)
    pr_number: int | None
    tier: Tier
    image_digest: str | None = None
    reason: str | None = None


class ProcessedEntry(_Frozen):
    """One line of ``state/processed.jsonl`` (D102, D288, ci-cd.md §1.2): a record, not a filter."""

    pr: int
    head_sha: str = Field(pattern=SHA_PATTERN)
    dispatch_run_id: int
    result: str = Field(min_length=1)
    run_id: str
    at: AwareDatetime

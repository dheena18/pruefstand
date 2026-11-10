"""Shared baseline-store types (review F8, D1123)."""

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

MAX_OVERRIDE_NOTE = 500


class PromotionOverride(BaseModel):
    """Who waived the promote guard with ``--allow-failed-gate``, when and why (D1123).

    Stored in the baseline's ``manifest.json`` (current and history) and in its ``index.json``
    entry, so an overridden baseline is never mistaken for one whose gate passed.

    Attributes:
        by: ``GITHUB_ACTOR`` when set, else the OS user name.
        at: UTC time of the promotion.
        reasons: What the guard would have refused the run for.
        note: The owner's ``--reason`` text.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    by: str = Field(min_length=1, max_length=64)
    at: AwareDatetime
    reasons: tuple[str, ...] = Field(min_length=1, max_length=20)
    note: str = Field(min_length=1, max_length=MAX_OVERRIDE_NOTE)

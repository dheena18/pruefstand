"""``AttacksConfig``: the ``attacks`` block of ``corpus.yaml`` (T4.6)."""

from pydantic import BaseModel, ConfigDict, Field

from pruefstand.core.models.attacks import InjectionPlacement


class AttacksConfig(BaseModel):
    """Injection documents placed into the customer tenants of a corpus.

    Attributes:
        seed: Seed of markers, anchors and wording; it is part of the ``attack_set_version``.
        seeds_per_tenant: Payloads used per customer tenant; with the six placements this is
            ``6 * seeds_per_tenant`` documents per tenant (8 gives 144 across three tenants).
        placements: Where the payload sits in a document (default: all six).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    seed: int
    seeds_per_tenant: int = Field(default=8, ge=1, le=30)
    placements: tuple[InjectionPlacement, ...] = Field(
        default=tuple(InjectionPlacement), min_length=1
    )

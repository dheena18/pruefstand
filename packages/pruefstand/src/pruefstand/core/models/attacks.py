"""Canary data models (interfaces §13). Planting and rotation live in ``attacks/`` (T2.6, T4.6)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from pruefstand.core.ids import DocId, TenantId


class Canary(BaseModel):
    """A planted secret that must never leave its tenant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    token: str
    tenant: TenantId
    doc_id: DocId
    kind: Literal["token", "semantic"]
    fact: str | None
    probe_question: str | None
    forbidden_answer: str | None


class CanaryRegistry(BaseModel):
    """All canaries of a corpus (or a release)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    canaries: tuple[Canary, ...]

    def foreign_to(self, tenant: TenantId) -> tuple[Canary, ...]:
        """Return the canaries whose tenant differs from ``tenant``, in registry order.

        Args:
            tenant: The tenant asking.

        Returns:
            Canaries planted for other tenants (all of them for an unknown tenant).
        """
        return tuple(c for c in self.canaries if c.tenant != tenant)

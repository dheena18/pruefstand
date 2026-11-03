"""The tenant filter: built in exactly one place, so its presence in every prefetch is testable."""

import re
from collections.abc import Collection

from pydantic import BaseModel, ConfigDict

from rag_demo.errors import UnknownTenantError

SHARED = "shared_public"
_TENANT = re.compile(r"[a-z][a-z0-9_]{0,63}")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MatchAny(_Frozen):
    """Qdrant ``match.any``: the payload value is one of ``any``."""

    any: tuple[str, ...]


class FieldCondition(_Frozen):
    """Qdrant field condition on one payload key."""

    key: str
    match: MatchAny


class Filter(_Frozen):
    """Qdrant filter with ``must`` conditions only (a ``should`` here would be the M9 bug)."""

    must: tuple[FieldCondition, ...]


def allowed_tenants(tenant_id: str, known: Collection[str] | None = None) -> frozenset[str]:
    """The tenants whose chunks ``tenant_id`` may see: itself and ``shared_public``.

    Args:
        tenant_id: The calling tenant.
        known: The tenants of the index; when given, anything else is unknown. Without it a
            tenant is valid when it is a lower-case slug (the API checks membership).

    Returns:
        ``{tenant_id, "shared_public"}``.

    Raises:
        UnknownTenantError: (a ``ValueError``) ``tenant_id`` is empty, not a slug, or unknown.

    Examples:
        >>> sorted(allowed_tenants("kanzlei_mueller"))
        ['kanzlei_mueller', 'shared_public']
        >>> sorted(allowed_tenants("shared_public"))
        ['shared_public']
    """
    if not _TENANT.fullmatch(tenant_id) or (known is not None and tenant_id not in known):
        msg = "unknown tenant"
        raise UnknownTenantError(msg)
    return frozenset({tenant_id, SHARED})


def tenant_filter(tenant_id: str) -> Filter:
    """The one filter every retrieval leg carries: ``tenant_id`` in the allowed tenants.

    Raises:
        ValueError: Unknown tenant (see ``allowed_tenants``).

    Examples:
        >>> tenant_filter("kanzlei_mueller").must[0].match.any
        ('kanzlei_mueller', 'shared_public')
    """
    tenants = tuple(sorted(allowed_tenants(tenant_id)))
    return Filter(must=(FieldCondition(key="tenant_id", match=MatchAny(any=tenants)),))

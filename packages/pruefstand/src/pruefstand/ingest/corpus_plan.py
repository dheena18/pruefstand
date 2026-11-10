"""Check a written corpus against its tenant plan (T2.5a): ``PlanCheck``.

A chunk carries only ``source`` and ``tenant``, not the ``law_abbrev`` or ``metadata`` the rules of
a plan may use. The check is therefore limited to what a chunk can show: the tenant must be one the
plan declares, and when every rule of the chunk's ``source`` names only that source (no
``law_abbrev``, no ``metadata``), the chunk must sit in the tenant of those rules. Sources that
the plan splits further, sources without a rule (private and attack documents bypass the rules)
and attack chunks are not decidable here and pass.
"""

from pruefstand.core.config import TenantPlan
from pruefstand.core.ids import TenantId
from pruefstand.core.models.corpus import Chunk


class PlanCheck:
    """Decides whether a chunk's tenant agrees with the plan (see the module docstring)."""

    def __init__(self, plan: TenantPlan) -> None:
        self._declared = set(plan.tenants)
        by_source: dict[str, set[TenantId]] = {}
        split: set[str] = set()
        for rule in plan.rules:
            if rule.source is None:
                continue
            if rule.law_abbrev is not None or rule.metadata:
                split.add(rule.source)
            by_source.setdefault(rule.source, set()).add(rule.tenant)
        self._fixed = {s: t for s, t in by_source.items() if s not in split}

    def problem(self, chunk: Chunk) -> str | None:
        """Return what is wrong with the tenant of ``chunk``, or ``None`` when it agrees."""
        if chunk.tenant not in self._declared:
            return f"chunk {chunk.chunk_id}: tenant {chunk.tenant!r} is not declared by the plan"
        wanted = self._fixed.get(chunk.source)
        if wanted is not None and not chunk.is_attack and chunk.tenant not in wanted:
            return (
                f"chunk {chunk.chunk_id}: source {chunk.source!r} belongs to "
                f"{sorted(wanted)} in the plan, not to {chunk.tenant!r}"
            )
        return None

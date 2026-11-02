"""Tenant assignment (T2.5): every document goes to exactly one tenant, decided by the plan.

The plan is data (``corpus.yaml``), not code. Matching is a dictionary lookup on ``source`` plus a
check of the remaining criteria, so the cost is linear in the number of documents. Tenant
isolation depends on this module being strict: a document that no rule claims, or that two rules
claim, stops the build, and one ``doc_id`` can never be assigned twice.
"""

from collections.abc import Iterable, Iterator

from pruefstand.core.config import TenantPlan
from pruefstand.core.config.build import UNASSIGNED_TENANT, TenantRule
from pruefstand.core.errors import ConfigError, DatasetError
from pruefstand.core.ids import DocId, TenantId
from pruefstand.core.models.corpus import Document


def _matches(rule: TenantRule, doc: Document) -> bool:
    """True if ``doc`` meets every criterion of ``rule``."""
    if rule.source is not None and rule.source != doc.source:
        return False
    if rule.law_abbrev is not None and rule.law_abbrev != doc.law_abbrev:
        return False
    return all(doc.metadata.get(key) == value for key, value in rule.metadata.items())


class _RuleIndex:
    """Rules grouped by their ``source`` so that a document only meets the rules that can match."""

    def __init__(self, plan: TenantPlan) -> None:
        self.default = plan.default_tenant
        self._by_source: dict[str, list[int]] = {}
        self._open: list[int] = []
        self._rules = plan.rules
        for number, rule in enumerate(plan.rules):
            if rule.source is None:
                self._open.append(number)
            else:
                self._by_source.setdefault(rule.source, []).append(number)

    def tenant_for(self, doc: Document) -> TenantId:
        """Return the tenant of ``doc``.

        Raises:
            ConfigError: No rule matches and there is no default, or several rules match.
        """
        candidates = (*self._by_source.get(doc.source, ()), *self._open)
        hits = [n for n in candidates if _matches(self._rules[n], doc)]
        if len(hits) > 1:
            msg = (
                f"{doc.doc_id}: matches more than one rule (rules {hits[0] + 1} and "
                f"{hits[1] + 1}); the rules of a tenant plan must be disjoint"
            )
            raise ConfigError(msg)
        if hits:
            tenant: TenantId = self._rules[hits[0]].tenant
            return tenant
        if self.default is None:
            msg = f"{doc.doc_id}: no rule matches (source {doc.source!r}) and no default_tenant"
            raise ConfigError(msg)
        return self.default


def assign_tenants(docs: Iterable[Document], plan: TenantPlan) -> Iterator[Document]:
    """Yield every document of ``docs`` with its ``tenant`` set by ``plan``.

    Only ``tenant`` changes. The input is consumed lazily.

    Args:
        docs: Documents as the loaders emit them (``tenant == "unassigned"``).
        plan: The tenant plan.

    Yields:
        A copy of each document with its tenant.

    Raises:
        ConfigError: A document already has a tenant, matches no rule (and the plan has no
            default) or matches more than one rule; the message names the ``doc_id``.
        DatasetError: A ``doc_id`` occurs twice (leakage guard: one document, one tenant).

    Examples:
        >>> from pruefstand.core.config.build import TenantPlan
        >>> plan = TenantPlan.model_validate(
        ...     {"tenants": ["a"], "rules": [{"tenant": "a", "source": "x"}]}
        ... )
        >>> doc = Document.model_construct(
        ...     doc_id="d1", tenant="unassigned", source="x", law_abbrev=None, metadata={}
        ... )
        >>> next(assign_tenants([doc], plan)).tenant
        'a'
    """
    index = _RuleIndex(plan)
    owner: dict[DocId, TenantId] = {}
    for doc in docs:
        if doc.tenant != UNASSIGNED_TENANT:
            msg = f"{doc.doc_id}: already has tenant {doc.tenant!r}; loaders emit 'unassigned'"
            raise ConfigError(msg)
        tenant = index.tenant_for(doc)
        if doc.doc_id in owner:
            msg = (
                f"{doc.doc_id}: occurs twice (tenants {owner[doc.doc_id]!r} and {tenant!r}); "
                "a document belongs to exactly one tenant"
            )
            raise DatasetError(msg)
        owner[doc.doc_id] = tenant
        yield doc.model_copy(update={"tenant": tenant})

"""Tenant isolation and the M8/M9 bug switches on the real index (Testcontainers).

Ported from T1.13 to ``rag_demo.retrieval`` (T3.5, D132): all four cases stay. They are the proof
that the seeded bugs still produce real leaks and that the filter itself (guard off) holds.
"""

import pytest
from rd_support import BERGMANN, own_and_public, prefetch_filters

from rag_demo.retrieval.testing import assert_tenant_scoped

pytestmark = pytest.mark.integration


def test_inside_filter_keeps_every_probe_inside_the_tenant(make_retriever, leak_probes) -> None:  # type: ignore[no-untyped-def]
    retriever, _ = make_retriever("rag.yaml", guard=False)  # the filter alone, not the safety net
    assert len(leak_probes) == 20
    for question in leak_probes:
        hits = retriever.retrieve("kanzlei_mueller", question, 4)
        assert own_and_public(hits), question


def test_inside_request_carries_the_filter_in_every_prefetch(make_retriever) -> None:  # type: ignore[no-untyped-def]
    retriever, transport = make_retriever("rag.yaml", guard=False)
    retriever.retrieve("kanzlei_mueller", BERGMANN, 4)
    (body,) = transport.bodies
    assert len(prefetch_filters(body)) == 2
    assert_tenant_scoped(body, "kanzlei_mueller")


def test_post_topk_leaks_the_other_tenants_chunk(make_retriever) -> None:  # type: ignore[no-untyped-def]
    retriever, _ = make_retriever("bugs/tenant_filter_post_topk.yaml")
    hits = retriever.retrieve("kanzlei_mueller", BERGMANN, 4)
    assert any(h.tenant_id == "versicherung_nord" for h in hits)


def test_unfiltered_shared_public_merge_leaks_a_foreign_chunk(make_retriever) -> None:  # type: ignore[no-untyped-def]
    retriever, transport = make_retriever("bugs/shared_public_unfiltered.yaml")
    hits = retriever.retrieve("kanzlei_mueller", BERGMANN, 4)
    assert any(h.tenant_id == "versicherung_nord" for h in hits)
    unscoped = []
    for body in transport.bodies:
        try:
            assert_tenant_scoped(body, "kanzlei_mueller")
        except AssertionError:
            unscoped.append(body)
    assert unscoped  # the second, unfiltered shared_public query of the M9 bug

"""Tenant isolation and the M8/M9 bug switches on the real index (Testcontainers)."""

import pytest
from rd_support import BERGMANN, own_and_public, prefetch_filters

pytestmark = pytest.mark.integration


def test_inside_filter_keeps_every_probe_inside_the_tenant(make_retriever, leak_probes) -> None:  # type: ignore[no-untyped-def]
    retriever, _ = make_retriever("rag.yaml")
    assert len(leak_probes) == 20
    for question in leak_probes:
        hits = retriever.retrieve("kanzlei_mueller", question, 4)
        assert own_and_public(hits), question


def test_inside_request_carries_the_filter_in_every_prefetch(make_retriever) -> None:  # type: ignore[no-untyped-def]
    retriever, transport = make_retriever("rag.yaml")
    retriever.retrieve("kanzlei_mueller", BERGMANN, 4)
    (body,) = transport.bodies
    assert len(body["prefetch"]) == 2  # type: ignore[arg-type]
    assert all(f is not None for f in prefetch_filters(body))


def test_post_topk_leaks_the_other_tenants_chunk(make_retriever) -> None:  # type: ignore[no-untyped-def]
    retriever, _ = make_retriever("bugs/tenant_filter_post_topk.yaml")
    hits = retriever.retrieve("kanzlei_mueller", BERGMANN, 4)
    assert any(h.tenant_id == "versicherung_nord" for h in hits)


def test_unfiltered_shared_public_merge_leaks_a_foreign_chunk(make_retriever) -> None:  # type: ignore[no-untyped-def]
    retriever, transport = make_retriever("bugs/shared_public_unfiltered.yaml")
    hits = retriever.retrieve("kanzlei_mueller", BERGMANN, 4)
    assert any(h.tenant_id == "versicherung_nord" for h in hits)
    assert any(all(f is None for f in prefetch_filters(b)) for b in transport.bodies)

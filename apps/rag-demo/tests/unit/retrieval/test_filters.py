"""The tenant filter and the allowed tenants (S1)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from rag_demo.retrieval.filters import SHARED, allowed_tenants, tenant_filter

SLUG = st.from_regex(r"[a-z][a-z0-9_]{0,63}", fullmatch=True)


def test_a_customer_sees_itself_and_shared_public() -> None:
    assert allowed_tenants("kanzlei_mueller") == {"kanzlei_mueller", "shared_public"}


def test_shared_public_sees_only_itself() -> None:
    assert allowed_tenants("shared_public") == {"shared_public"}


@pytest.mark.parametrize("tenant", ["", " ", "Kanzlei", "a b", "x" * 65, "../etc", "ä", "1abc"])
def test_a_malformed_tenant_is_unknown(tenant: str) -> None:
    with pytest.raises(ValueError, match="unknown tenant"):
        allowed_tenants(tenant)
    with pytest.raises(ValueError, match="unknown tenant"):
        tenant_filter(tenant)


def test_a_tenant_outside_the_known_set_is_unknown() -> None:
    assert allowed_tenants("a", known={"a", "b"}) == {"a", "shared_public"}
    with pytest.raises(ValueError, match="unknown tenant"):
        allowed_tenants("c", known={"a", "b"})


def test_the_filter_is_one_must_with_match_any() -> None:
    flt = tenant_filter("kanzlei_mueller")
    assert flt.model_dump() == {
        "must": (
            {
                "key": "tenant_id",
                "match": {"any": ("kanzlei_mueller", "shared_public")},
            },
        )
    }
    assert "should" not in flt.model_dump_json()


def test_the_filter_for_shared_public_lists_it_once() -> None:
    assert tenant_filter(SHARED).must[0].match.any == ("shared_public",)


@given(SLUG)
def test_every_slug_is_allowed_with_shared_public_and_the_filter_matches_exactly_them(
    tenant: str,
) -> None:
    allowed = allowed_tenants(tenant)
    assert SHARED in allowed
    assert tenant in allowed
    assert set(tenant_filter(tenant).must[0].match.any) == allowed

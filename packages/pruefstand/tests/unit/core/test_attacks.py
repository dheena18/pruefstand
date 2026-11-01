import pytest
from pydantic import ValidationError

from pruefstand.core.ids import DocId, TenantId
from pruefstand.core.models.attacks import Canary, CanaryRegistry


def canary(token: str, tenant: str) -> Canary:
    return Canary(
        token=token,
        tenant=TenantId(tenant),
        doc_id=DocId(f"{tenant}-doc"),
        kind="token",
        fact=None,
        probe_question=None,
        forbidden_answer=None,
    )


REGISTRY = CanaryRegistry(
    canaries=(
        canary("CANARY-KM-000001", "kanzlei_mueller"),
        canary("CANARY-VN-000002", "versicherung_nord"),
        canary("CANARY-KM-000003", "kanzlei_mueller"),
        canary("CANARY-VN-000004", "versicherung_nord"),
    )
)


def test_foreign_to_returns_other_tenants_in_order() -> None:
    foreign = REGISTRY.foreign_to(TenantId("kanzlei_mueller"))
    assert [c.token for c in foreign] == ["CANARY-VN-000002", "CANARY-VN-000004"]
    assert all(c.tenant == "versicherung_nord" for c in foreign)


def test_foreign_to_unknown_tenant_returns_all() -> None:
    assert REGISTRY.foreign_to(TenantId("someone_else")) == REGISTRY.canaries


def test_empty_registry() -> None:
    assert CanaryRegistry(canaries=()).foreign_to(TenantId("x")) == ()


def test_extra_field_is_an_error() -> None:
    with pytest.raises(ValidationError, match="extra"):
        CanaryRegistry.model_validate({"canaries": [], "version": 1})
    with pytest.raises(ValidationError, match="extra"):
        Canary.model_validate({**canary("CANARY-KM-000001", "k").model_dump(), "x": 1})


def test_kind_is_restricted() -> None:
    with pytest.raises(ValidationError, match="kind"):
        Canary.model_validate({**canary("CANARY-KM-000001", "k").model_dump(), "kind": "other"})


def test_semantic_canary_round_trip() -> None:
    sem = Canary.model_validate(
        {
            "token": "CANARY-KM-000009",
            "tenant": "kanzlei_mueller",
            "doc_id": "km-9",
            "kind": "semantic",
            "fact": "Das Aktenzeichen lautet 4711.",
            "probe_question": "Wie lautet das Aktenzeichen?",
            "forbidden_answer": "4711",
        }
    )
    registry = CanaryRegistry(canaries=(sem,))
    assert CanaryRegistry.model_validate_json(registry.model_dump_json()) == registry
    assert CanaryRegistry.model_validate_json(REGISTRY.model_dump_json()) == REGISTRY

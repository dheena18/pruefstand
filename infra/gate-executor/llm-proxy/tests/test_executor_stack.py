"""The executor compose stack (T6.2a S4, D1020): qdrant and rerank-cpu next to llm-proxy.

Static checks of ``infra/gate-executor/compose.executor.yml``; the live network checks are the
T6.2a ``[DOCKER]`` Done-when items.
"""

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[4]
COMPOSE: dict[str, Any] = yaml.safe_load(
    (ROOT / "infra/gate-executor/compose.executor.yml").read_text(encoding="utf-8")
)
SERVICES: dict[str, Any] = COMPOSE["services"]
ROOT_COMPOSE: dict[str, Any] = yaml.safe_load((ROOT / "docker-compose.yml").read_text("utf-8"))


def test_the_stack_has_qdrant_rerank_cpu_and_llm_proxy() -> None:
    assert set(SERVICES) == {"qdrant", "rerank-cpu", "llm-proxy"}


def test_qdrant_uses_the_pinned_image_of_the_root_compose() -> None:
    assert SERVICES["qdrant"]["image"] == ROOT_COMPOSE["services"]["qdrant"]["image"]
    assert "@sha256:" in SERVICES["qdrant"]["image"]


def test_qdrant_needs_its_api_key_and_jwt_rbac() -> None:
    env = SERVICES["qdrant"]["environment"]
    assert env["QDRANT__SERVICE__API_KEY"].startswith("${QDRANT_API_KEY:?")
    assert env["QDRANT__SERVICE__JWT_RBAC"] == "true"  # scoped candidate keys (S5)


def test_qdrant_publishes_loopback_default_ports_only() -> None:
    ports = SERVICES["qdrant"]["ports"]
    assert ports == [
        "127.0.0.1:${QDRANT_HTTP_PORT:-6333}:6333",
        "127.0.0.1:${QDRANT_GRPC_PORT:-6334}:6334",
    ]


def test_qdrant_storage_is_under_pruefstand_home_not_the_data_root() -> None:
    (volume,) = SERVICES["qdrant"]["volumes"]
    assert volume.startswith("${PRUEFSTAND_HOME:?")
    assert volume.endswith("/qdrant:/qdrant/storage")
    assert "DATA_ROOT" not in volume


def test_rerank_cpu_is_internal_offline_and_unpublished() -> None:
    rerank = SERVICES["rerank-cpu"]
    assert rerank["networks"] == ["gate-net"]
    assert rerank.get("ports", []) == []
    assert rerank["environment"]["HF_HUB_OFFLINE"] == "1"  # gate-net has no egress
    assert rerank["volumes"] == ["rerank_models:/models:ro"]
    assert COMPOSE["volumes"]["rerank_models"] == {
        "external": True,
        "name": "pruefstand-rerank-models",
    }


def test_only_llm_proxy_reaches_proxy_egress_and_the_candidate_net_is_internal() -> None:
    for name, svc in SERVICES.items():
        assert ("proxy-egress" in svc["networks"]) is (name == "llm-proxy"), name
        assert "gate-net" in svc["networks"], name
        assert svc.get("network_mode") != "host", name
    assert COMPOSE["networks"]["gate-net"]["internal"] is True
    assert COMPOSE["networks"]["exec-host"].get("internal") is not True


def test_qdrant_is_the_only_service_with_host_ports() -> None:
    assert [n for n, s in SERVICES.items() if s.get("ports")] == ["qdrant"]
    assert SERVICES["qdrant"]["networks"] == ["gate-net", "exec-host"]


def test_every_service_has_a_healthcheck_and_no_privileges() -> None:
    for name, svc in SERVICES.items():
        assert "healthcheck" in svc, name
        assert svc.get("privileged") is not True, name
        assert "no-new-privileges:true" in svc.get("security_opt", []), name

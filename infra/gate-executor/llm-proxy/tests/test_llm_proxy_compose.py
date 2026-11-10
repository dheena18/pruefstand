"""Static checks of the llm-proxy service and image (D242, CLAUDE.md §8)."""

from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parents[1]
COMPOSE: dict[str, Any] = yaml.safe_load((HERE.parent / "compose.executor.yml").read_text("utf-8"))
SERVICE: dict[str, Any] = COMPOSE["services"]["llm-proxy"]
DOCKERFILE = (HERE / "Dockerfile").read_text("utf-8")


def test_llm_proxy_is_on_gate_net_and_proxy_egress_only_without_ports() -> None:
    assert sorted(SERVICE["networks"]) == ["gate-net", "proxy-egress"]
    assert "ports" not in SERVICE
    assert "network_mode" not in SERVICE
    assert "extra_hosts" not in SERVICE


def test_networks_gate_net_internal_and_proxy_egress_external() -> None:
    nets = COMPOSE["networks"]
    assert nets["gate-net"] == {"name": "gate-net", "internal": True}
    assert nets["proxy-egress"]["external"] is True


def test_upstream_is_the_tunnel_on_the_bridge_gateway_only() -> None:
    assert SERVICE["environment"]["LLM_PROXY_UPSTREAM"] == "http://172.17.0.1:11434"
    assert "LLM_PROXY_UPSTREAM=http://172.17.0.1:11434" in DOCKERFILE


def test_container_is_locked_down() -> None:
    assert SERVICE["read_only"] is True
    assert SERVICE["cap_drop"] == ["ALL"]
    assert SERVICE["security_opt"] == ["no-new-privileges:true"]
    assert not str(SERVICE["user"]).startswith("0")
    assert "privileged" not in SERVICE
    assert "volumes" not in SERVICE
    assert SERVICE["pids_limit"] == 128
    assert SERVICE["mem_limit"] == "256m"


def test_no_service_publishes_a_port_or_uses_the_host_network() -> None:
    for name, svc in COMPOSE["services"].items():
        assert "ports" not in svc, name
        assert svc.get("network_mode") != "host", name


def test_dockerfile_pinned_non_root_with_healthcheck() -> None:
    froms = [line for line in DOCKERFILE.splitlines() if line.startswith("FROM python")]
    assert froms
    assert all("@sha256:" in line for line in froms)
    assert "\nUSER 10001\n" in DOCKERFILE
    assert "HEALTHCHECK" in DOCKERFILE
    assert "127.0.0.1:11500/health" in DOCKERFILE
    assert "pip install" not in DOCKERFILE


def test_image_contains_every_proxy_module() -> None:
    modules = sorted(p.name for p in HERE.glob("llm_proxy*.py"))
    assert len(modules) == 4
    for name in modules:
        assert "COPY --from=builder" in DOCKERFILE
        assert DOCKERFILE.count(name) >= 3, name  # builder COPY, py_compile, runtime COPY

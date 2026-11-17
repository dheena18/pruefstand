"""The demo compose file (T8.4 S6b, ADR-0012, P2.2): isolation, pins and the resource budget."""

import re
from pathlib import Path
from typing import Any

import yaml

COMPOSE = Path(__file__).resolve().parents[2] / "infra" / "deploy" / "demo" / "compose.yml"
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")
UNITS = {"m": 1 / 1024, "g": 1.0}


def _load() -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    return doc


def _services(profile: str) -> dict[str, dict[str, Any]]:
    return {n: s for n, s in _load()["services"].items() if profile in s["profiles"]}


def _gb(value: str) -> float:
    return float(value[:-1]) * UNITS[value[-1]]


def _cpus(service: dict[str, Any]) -> float:
    raw = str(service["cpus"])
    return float(re.sub(r"^\$\{[A-Z_]+:-(.+)\}$", r"\1", raw))


def test_every_service_is_on_the_internal_network() -> None:
    doc = _load()
    assert doc["networks"]["demo-net"]["internal"] is True
    # the production default stays 10.232.0.0/24; the e2e project overrides it (no shared pool)
    assert doc["networks"]["demo-net"]["ipam"]["config"] == [
        {"subnet": "${DEMO_NET_SUBNET:-10.232.0.0/24}"}
    ]
    for name, service in doc["services"].items():
        assert "demo-net" in service["networks"], name


def test_only_the_e2e_instance_has_egress_capable_network_and_a_host_port() -> None:
    doc = _load()
    for name, service in doc["services"].items():
        has_edge = "e2e-edge" in service["networks"]
        assert has_edge == (name == "rag-demo-e2e"), name
        assert ("ports" in service) == (name == "rag-demo-e2e"), name
    assert "demo-edge" not in doc["networks"]
    assert doc["services"]["rag-demo-e2e"]["ports"] == ["127.0.0.1:${E2E_PORT:-8091}:8000"]
    assert doc["services"]["rag-demo-e2e"]["profiles"] == ["e2e"]


def test_the_test_reset_exists_only_on_the_e2e_instance() -> None:
    for name, service in _load()["services"].items():
        env = service.get("environment") or {}
        assert ("DEMO_TEST_RESET" in env) == (name == "rag-demo-e2e"), name
    env = _load()["services"]["rag-demo-e2e"]["environment"]
    assert (env["TRUSTED_PROXY_HOPS"], env["DEMO_TEST_RESET"]) == ("0", "1")
    assert _load()["services"]["rag-demo"]["environment"]["TRUSTED_PROXY_HOPS"] == "1"


def test_third_party_images_are_pinned_and_built_ones_are_not_tagged() -> None:
    for name, service in _load()["services"].items():
        if "build" in service:
            assert "image" not in service, name
        else:
            assert DIGEST.search(service["image"]), name


def test_every_service_has_a_healthcheck_and_no_new_privileges() -> None:
    for name, service in _load()["services"].items():
        assert service["healthcheck"].get("disable") is not True, name
        assert service["healthcheck"]["test"], name
        assert "no-new-privileges:true" in service["security_opt"], name


def test_the_app_containers_drop_capabilities_and_have_a_read_only_root() -> None:
    for name in ("rag-demo", "rag-demo-e2e", "index"):
        service = _load()["services"][name]
        assert service["cap_drop"] == ["ALL"], name
        assert service["read_only"] is True, name


def test_the_demo_profile_fits_the_adr_budget_and_the_e2e_project_is_its_own() -> None:
    steady = {n: s for n, s in _services("demo").items() if n != "index"}  # index is a one-shot
    cpus = sum(_cpus(s) for s in steady.values())
    mem = sum(_gb(s["mem_limit"]) for s in steady.values())
    assert (cpus, mem) == (4.0, 7.0)  # ADR-0012: 4 vCPU / 8 GB
    e2e = {n: s for n, s in _services("e2e").items() if n != "index"}
    assert (
        sum(_cpus(s) for s in e2e.values()),
        sum(_gb(s["mem_limit"]) for s in e2e.values()),
    ) == (4.0, 7.0)
    assert (2 * cpus, 2 * mem) == (
        8.0,
        14.0,
    )  # demo + e2e together: within the VM's 24 GB, over ADR-0012


def test_the_demo_profile_publishes_no_port_and_uses_the_public_config() -> None:
    demo = _services("demo")
    assert set(demo) == {"qdrant", "llm", "embed", "index", "rag-demo"}
    assert not [n for n, s in demo.items() if "ports" in s]
    for name in ("rag-demo", "rag-demo-e2e", "index"):
        assert _load()["services"][name]["environment"]["RAG_CONFIG"].endswith("rag.public.yaml")

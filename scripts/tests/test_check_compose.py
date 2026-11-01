from pathlib import Path

import check_compose
import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
DIGEST = "sha256:" + "a" * 64
HEALTH = {"test": ["CMD", "true"], "interval": "10s"}


def _compose(
    overrides: dict[str, object] | None = None, drop: tuple[str, ...] = ()
) -> dict[str, object]:
    service: dict[str, object] = {"image": f"qdrant/qdrant:v1.20.0@{DIGEST}", "healthcheck": HEALTH}
    service.update(overrides or {})
    for key in drop:
        del service[key]
    return {"services": {"qdrant": service}}


def _problems(**overrides: object) -> list[str]:
    return check_compose.check_compose(_compose(overrides))


def test_clean_service_passes() -> None:
    assert _problems() == []


def test_image_without_digest_fails() -> None:
    assert "qdrant: image not pinned by digest" in _problems(image="qdrant/qdrant:v1.12.0")


def test_build_without_image_is_exempt_from_digest() -> None:
    assert check_compose.check_compose(_compose({"build": {"context": "."}}, drop=("image",))) == []


def test_all_interfaces_port_fails() -> None:
    assert any("binds all interfaces" in p for p in _problems(ports=["6333:6333"]))


def test_bare_container_port_fails() -> None:
    assert any("binds all interfaces" in p for p in _problems(ports=["6333"]))


def test_non_loopback_ip_fails() -> None:
    assert any("binds all interfaces" in p for p in _problems(ports=["0.0.0.0:6333:6333"]))


def test_literal_host_port_fails() -> None:
    assert any("literal host port" in p for p in _problems(ports=["127.0.0.1:6333:6333"]))


def test_variable_host_port_passes() -> None:
    assert _problems(ports=["127.0.0.1:${QDRANT_HTTP_PORT:-6333}:6333"]) == []


def test_variable_without_port_suffix_fails() -> None:
    bad = ["127.0.0.1:${QDRANT:-6333}:6333"]
    assert any("literal host port" in p for p in _problems(ports=bad))


def test_long_syntax_ports() -> None:
    good = {"target": 6333, "published": "${QDRANT_HTTP_PORT:-6333}", "host_ip": "127.0.0.1"}
    assert _problems(ports=[good]) == []
    assert any("binds all interfaces" in p for p in _problems(ports=[{**good, "host_ip": "::"}]))
    assert any("literal host port" in p for p in _problems(ports=[{**good, "published": 6333}]))


def test_host_network_without_ports_passes() -> None:
    assert _problems(network_mode="host") == []


def test_missing_healthcheck_fails() -> None:
    assert "qdrant: no healthcheck" in check_compose.check_compose(_compose(drop=("healthcheck",)))


def test_disabled_healthcheck_fails() -> None:
    assert "qdrant: no healthcheck" in _problems(healthcheck={"disable": True})


def test_literal_secret_in_list_env_fails() -> None:
    assert any("secret" in p for p in _problems(environment=["HF_TOKEN=abc"]))


def test_literal_secret_in_mapping_env_fails() -> None:
    assert any("secret" in p for p in _problems(environment={"API_KEY": "abc"}))


def test_variable_secret_passes() -> None:
    assert _problems(environment=["HF_TOKEN=${HF_TOKEN}"]) == []
    assert _problems(environment={"DB_PASSWORD": "${DB_PASSWORD:?set it}"}) == []


def test_empty_or_bare_secret_names_pass() -> None:
    assert _problems(environment=["HF_TOKEN", "API_KEY="]) == []


def test_non_secret_literal_passes() -> None:
    assert _problems(environment=["QDRANT__LOG_LEVEL=INFO"]) == []


def test_yaml_reset_tag_is_tolerated(tmp_path: Path) -> None:
    path = tmp_path / "compose.executor.yml"
    path.write_text(
        f"services:\n  qdrant:\n    image: q@{DIGEST}\n    healthcheck: {{test: [CMD, 'true']}}\n"
        "    ports: !reset []\n",
        encoding="utf-8",
    )
    assert check_compose.check_file(path) == []


def test_main_reports_and_exits_nonzero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "docker-compose.yml"
    path.write_text(yaml.safe_dump(_compose({"image": "qdrant/qdrant:latest"})), encoding="utf-8")
    assert check_compose.main([str(path)]) == 1
    assert "image not pinned by digest" in capsys.readouterr().out


def test_repo_compose_file_passes() -> None:
    assert check_compose.check_file(REPO / "docker-compose.yml") == []


def test_digest_must_be_64_hex_at_the_end() -> None:
    for bad in ("x@sha256:abc", f"x@{DIGEST}-extra", "x@sha256:" + "G" * 64, "x@sha256:"):
        assert "qdrant: image not pinned by digest" in _problems(image=bad)
    assert _problems(image=f"x:1@{DIGEST}") == []


def test_none_healthcheck_counts_as_missing() -> None:
    for test in (["NONE"], "NONE"):
        assert "qdrant: no healthcheck" in _problems(healthcheck={"test": test})


def test_secret_with_literal_default_fails() -> None:
    for value in ("${HF_TOKEN:-abc}", "${HF_TOKEN-abc}"):
        assert any("literal default" in p for p in _problems(environment={"HF_TOKEN": value}))
    assert any("literal default" in p for p in _problems(environment=["API_KEY=${API_KEY:-x}"]))


def test_secret_with_empty_default_or_required_marker_passes() -> None:
    for value in ("${HF_TOKEN:-}", "${HF_TOKEN-}", "${HF_TOKEN:?set it}", "${HF_TOKEN}"):
        assert _problems(environment={"HF_TOKEN": value}) == []


def test_non_secret_default_may_be_literal() -> None:
    assert _problems(environment={"LOG_LEVEL": "${LOG_LEVEL:-info}"}) == []


def test_bracketed_ipv6_host_is_rejected_clearly() -> None:
    for spec in ("[::1]:${QDRANT_HTTP_PORT:-6333}:6333", "[::]:${QDRANT_HTTP_PORT:-6333}:6333"):
        problems = _problems(ports=[spec])
        assert any("IPv6" in p and "binds all interfaces" in p for p in problems)


def test_secret_with_literal_prefix_or_suffix_next_to_a_variable_fails() -> None:
    for value in ("pw${X}", "${X}suffix", "Bearer ${TOKEN}", "a${X:-}b"):
        assert any("literal" in p for p in _problems(environment={"API_TOKEN": value})), value


def test_secret_made_only_of_variables_passes() -> None:
    for value in ("${A}${B}", "${A:?need}", "${A:-}", "${A:-${B}}"):
        assert _problems(environment={"API_TOKEN": value}) == [], value


def test_healthcheck_without_a_usable_test_counts_as_missing() -> None:
    cases: list[dict[str, object]] = [{"test": []}, {"interval": "10s"}, {"test": ""}, {}]
    for health in cases:
        assert "qdrant: no healthcheck" in _problems(healthcheck=health), health


def test_healthcheck_without_test_is_accepted_when_the_service_extends_another() -> None:
    assert _problems(healthcheck={"interval": "5s"}, extends={"service": "base"}) == []

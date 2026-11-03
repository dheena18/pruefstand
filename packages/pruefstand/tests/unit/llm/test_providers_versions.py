"""Endpoint and catalogue loading, version probes and the epoch-file error branches."""

from pathlib import Path

import pytest
import yaml
from testsupport.gpu_files import OPTIONS, write_catalogue, write_endpoints
from testsupport.llm_scenarios import DictCache, echo_request
from testsupport.loopback_script import serve_script

from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.core.errors import ConfigError
from pruefstand.core.models.llm import LLMRequest
from pruefstand.llm.backends.litellm import LiteLLMBackend
from pruefstand.llm.budget import Budget
from pruefstand.llm.cache_epochs import current_epoch, drift_file, read_drift
from pruefstand.llm.client import LLMClient
from pruefstand.llm.costs import gpu_seconds
from pruefstand.llm.factory import build_backend
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.providers import catalogue_entry, catalogue_options, endpoint_env, server_gpus
from pruefstand.llm.recorder import CallRecorder

MODEL = "ollama/judge-x:1b"
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, origin: str, digest: str | None
) -> None:
    entry = {"id": MODEL, "engine": "ollama", "tag": "judge-x:1b", "options": OPTIONS}
    if digest:
        entry["digest"] = digest
    catalogue = tmp_path / "models.yaml"
    catalogue.write_text(yaml.safe_dump({"models": [entry]}), encoding="utf-8")
    endpoints = write_endpoints(tmp_path / "ep.yaml", {"judge": ("T_URL", MODEL)})
    monkeypatch.setenv("PRUEFSTAND_GPU_CATALOGUE", str(catalogue))
    monkeypatch.setenv("PRUEFSTAND_GPU_ENDPOINTS", str(endpoints))
    monkeypatch.setenv("T_URL", origin)


def _client(cache: DictCache) -> LLMClient:
    policy = LLMPolicyConfig()
    backend = build_backend(ModelRef(id=MODEL, family="gemma"), policy=policy)
    return LLMClient(backend, cache, Budget(None, None), CallRecorder(), LLMPolicy(policy))


def _req() -> LLMRequest:
    return echo_request().model_copy(update={"model": MODEL})


async def test_the_ollama_version_is_tag_and_digest_and_changes_the_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = DictCache()
    for digest, posts in ((DIGEST_A, 1), (DIGEST_A, 0), (DIGEST_B, 1)):
        tags = {"models": [{"name": "judge-x:1b", "digest": f"sha256:{digest}"}]}
        with serve_script(tags=tags) as (origin, state):
            _setup(tmp_path, monkeypatch, origin, DIGEST_A)
            await _client(cache).complete(_req())
            assert state.posts() == posts


async def test_a_model_the_server_does_not_list_has_no_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with serve_script(tags={"models": []}) as (origin, _):
        _setup(tmp_path, monkeypatch, origin, None)
        backend = build_backend(ModelRef(id=MODEL, family="gemma"), policy=LLMPolicyConfig())
        assert isinstance(backend, LiteLLMBackend)
        assert await backend.resolve_version(MODEL) is None
        assert await backend.resolve_version("github/x") is None


def test_endpoint_lookup_and_catalogue_errors(tmp_path: Path) -> None:
    endpoints = write_endpoints(tmp_path / "ep.yaml", {"judge": ("T_URL", MODEL)})
    assert endpoint_env(MODEL, endpoints) == "T_URL"
    assert endpoint_env("ollama/other:1", endpoints) == "OLLAMA_GPU0_URL"
    bad = tmp_path / "bad.yaml"
    bad.write_text("endpoints: 3", encoding="utf-8")
    with pytest.raises(ConfigError, match="endpoints"):
        endpoint_env(MODEL, bad)
    bad.write_text("[1, 2", encoding="utf-8")
    with pytest.raises(ConfigError, match="YAML"):
        endpoint_env(MODEL, bad)
    bad.write_text("- a", encoding="utf-8")
    with pytest.raises(ConfigError, match="mapping"):
        endpoint_env(MODEL, bad)
    bad.write_text("x: " + "a" * 1_100_000, encoding="utf-8")
    with pytest.raises(ConfigError, match="larger"):
        endpoint_env(MODEL, bad)


def test_catalogue_validation(tmp_path: Path) -> None:
    good = write_catalogue(tmp_path / "m.yaml", {MODEL: OPTIONS})
    assert dict(catalogue_options(MODEL, good)) == OPTIONS
    assert catalogue_entry(MODEL, good).tag == "judge-x:1b"
    with pytest.raises(ConfigError, match="not in the GPU catalogue"):
        catalogue_entry("ollama/zzz:1", good)
    with pytest.raises(ConfigError, match="cannot be read"):
        catalogue_entry(MODEL, tmp_path / "missing.yaml")
    no_models = tmp_path / "n.yaml"
    no_models.write_text("models: 3", encoding="utf-8")
    with pytest.raises(ConfigError, match="models"):
        catalogue_entry(MODEL, no_models)
    short = tmp_path / "s.yaml"
    short.write_text(
        yaml.safe_dump({"models": [{"id": MODEL, "engine": "ollama", "options": {"num_ctx": 1}}]}),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="options"):
        catalogue_entry(MODEL, short)


def test_gpu_seconds_by_server_and_unknown_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    both = tmp_path / "m.yaml"
    both.write_text(
        yaml.safe_dump(
            {"models": [{"id": MODEL, "engine": "ollama", "server": "all", "options": OPTIONS}]}
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PRUEFSTAND_GPU_CATALOGUE", str(both))
    assert server_gpus("all") == 2
    assert gpu_seconds(MODEL, 1000.0) == pytest.approx(2.0)
    with pytest.raises(ConfigError):
        gpu_seconds("ollama/unlisted:1", 1.0)


def test_epoch_and_drift_files_reject_garbage(tmp_path: Path) -> None:
    (tmp_path / "cache_epochs.json").write_text('{"m": -1}', encoding="utf-8")
    with pytest.raises(ConfigError, match="non-negative"):
        current_epoch(tmp_path, "m")
    drift_file(tmp_path).write_text('{"model": 3}', encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid"):
        read_drift(tmp_path)
    (tmp_path / "cache_epochs.json").write_text("[" * 2_000_000, encoding="utf-8")
    with pytest.raises(ConfigError, match="larger"):
        current_epoch(tmp_path, "m")

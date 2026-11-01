from pathlib import Path

import pytest

from pruefstand.core.settings import PruefstandSettings

ENV_NAMES = (
    "GITHUB_TOKEN",
    "PRUEFSTAND_GITHUB_TOKEN",
    "PRUEFSTAND_GH_MODELS_TOKEN",
    "HF_TOKEN",
    "PRUEFSTAND_HF_TOKEN",
    "PRUEFSTAND_JUDGE_BASE_URL",
    "PRUEFSTAND_LOG_JSON",
    "PRUEFSTAND_CACHE_DIR",
    "PRUEFSTAND_HOME",
    "PRUEFSTAND_GPU_ENDPOINTS",
    "PRUEFSTAND_GPU_CATALOGUE",
    "CI",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def make() -> PruefstandSettings:
    return PruefstandSettings(_env_file=None)


def test_gh_models_token_reads_only_its_own_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRUEFSTAND_GH_MODELS_TOKEN", "ghp_m")
    settings = make()
    assert settings.gh_models_token is not None
    assert settings.gh_models_token.get_secret_value() == "ghp_m"
    assert settings.github_token is None


def test_bare_github_token_never_reaches_gh_models_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    settings = make()
    assert settings.github_token is not None
    assert settings.github_token.get_secret_value() == "ghp_x"
    assert settings.gh_models_token is None  # D333


def test_repr_hides_every_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRUEFSTAND_GH_MODELS_TOKEN", "ghp_m_secret")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x_secret")
    monkeypatch.setenv("HF_TOKEN", "hf_secret")
    settings = make()
    for text in (repr(settings), str(settings), settings.model_dump_json()):
        assert "ghp_m_secret" not in text
        assert "ghp_x_secret" not in text
        assert "hf_secret" not in text


def test_hf_token_prefers_hf_token_then_the_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRUEFSTAND_HF_TOKEN", "b")
    alias_only = make()
    assert alias_only.hf_token is not None
    assert alias_only.hf_token.get_secret_value() == "b"
    monkeypatch.setenv("HF_TOKEN", "a")
    both = make()
    assert both.hf_token is not None
    assert both.hf_token.get_secret_value() == "a"


def test_tokens_default_to_none() -> None:
    settings = make()
    assert settings.github_token is None
    assert settings.gh_models_token is None
    assert settings.hf_token is None
    assert settings.judge_base_url is None


def test_gpu_files_default_and_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    settings = make()
    assert settings.gpu_endpoints_file == Path("infra/gpu/endpoints.yaml")
    assert settings.gpu_catalogue_file == Path("infra/gpu/models.yaml")
    endpoints, catalogue = tmp_path / "e.yaml", tmp_path / "m.yaml"
    monkeypatch.setenv("PRUEFSTAND_GPU_ENDPOINTS", str(endpoints))
    monkeypatch.setenv("PRUEFSTAND_GPU_CATALOGUE", str(catalogue))
    settings = make()
    assert settings.gpu_endpoints_file == endpoints
    assert settings.gpu_catalogue_file == catalogue


def test_judge_base_url_and_log_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRUEFSTAND_JUDGE_BASE_URL", "http://localhost:8080/v1")
    monkeypatch.setenv("PRUEFSTAND_LOG_JSON", "false")
    settings = make()
    assert settings.judge_base_url == "http://localhost:8080/v1"
    assert settings.log_json is False


def test_log_json_defaults_to_true_in_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    assert make().log_json is False
    monkeypatch.setenv("CI", "true")
    assert make().log_json is True


def test_cache_dir_default_and_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PRUEFSTAND_HOME", str(tmp_path))
    assert make().cache_dir == tmp_path / "cache"
    monkeypatch.setenv("PRUEFSTAND_CACHE_DIR", str(tmp_path / "other"))
    assert make().cache_dir == tmp_path / "other"


def test_empty_variables_fall_back_to_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # .env.example ships `PRUEFSTAND_CACHE_DIR=` and `PRUEFSTAND_LOG_JSON=` empty.
    monkeypatch.setenv("PRUEFSTAND_HOME", str(tmp_path))
    monkeypatch.setenv("PRUEFSTAND_CACHE_DIR", "")
    monkeypatch.setenv("PRUEFSTAND_LOG_JSON", "")
    settings = make()
    assert settings.cache_dir == tmp_path / "cache"
    assert settings.log_json is False


def test_unrelated_environment_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRUEFSTAND_SOMETHING_ELSE", "1")
    make()

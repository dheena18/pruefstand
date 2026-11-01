import subprocess
import sys

import pytest

from pruefstand.adapters import HttpTargetAdapter, build_adapter
from pruefstand.core.config import HttpTargetConfig, TargetConfig
from pruefstand.core.errors import ConfigError


def test_http_type_builds_http_adapter() -> None:
    adapter = build_adapter(TargetConfig(type="http", url="http://localhost:8000"))
    assert isinstance(adapter, HttpTargetAdapter)


def test_http_specialisation_builds_http_adapter() -> None:
    cfg = HttpTargetConfig(type="http", url="https://rag.example.org", timeout_s=5)
    assert isinstance(build_adapter(cfg), HttpTargetAdapter)


def test_unknown_type_raises_config_error() -> None:
    cfg = TargetConfig.model_construct(type="langchain", url="http://x", auth_env=None, timeout_s=1)
    with pytest.raises(ConfigError, match="langchain"):
        build_adapter(cfg)


def test_importing_adapters_does_not_import_sibling_layers() -> None:
    code = (
        "import sys, pruefstand.adapters; "
        "bad = [m for m in sys.modules if m.startswith((pruefstand.store, pruefstand.judges))]; "
        "sys.exit(1 if bad else 0)"
    )
    result = subprocess.run([sys.executable, "-I", "-c", code], check=False, capture_output=True)
    assert result.returncode == 0, result.stderr.decode()

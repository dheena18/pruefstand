"""Both conftests must register the scrubbing hooks (the live one scrubs `make cassettes`)."""

import asyncio
import importlib.util
from pathlib import Path
from typing import Any

import pytest
import vcr  # type: ignore[import-untyped]  # vcrpy ships no stubs
from testsupport.llm_scenarios import echo_request
from testsupport.loopback import serve
from testsupport.vcr_scrub import scrub_request, scrub_response

from pruefstand.llm.backends.litellm import LiteLLMBackend

TESTS = Path(__file__).resolve().parents[2]
CONFTESTS = {
    "unit": TESTS / "unit" / "llm" / "conftest.py",
    "live": TESTS / "live" / "llm" / "conftest.py",
}
MODEL = "openai_compatible_local/loop"


def _config(path: Path) -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location(f"conftest_{path.parent.parent.name}", path)
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fixture = module.vcr_config
    func = getattr(fixture, "__wrapped__", None) or fixture._get_wrapped_function()
    return dict(func())


@pytest.mark.parametrize("which", ["unit", "live"])
def test_conftest_registers_the_scrub_hooks(which: str) -> None:
    config = _config(CONFTESTS[which])
    assert config["before_record_request"] is scrub_request
    assert config["before_record_response"] is scrub_response


@pytest.mark.parametrize("which", ["unit", "live"])
def test_conftest_config_scrubs_a_real_recording(tmp_path: Path, which: str) -> None:
    config = _config(CONFTESTS[which])
    hooks = {k: v for k, v in config.items() if k.startswith("before_")}
    headers = {"Set-Cookie": "session=SECRETCOOKIE123", "X-Echo": "Bearer ghp_abcdefghijklmnop1234"}
    path = tmp_path / "c.yaml"
    with serve(headers=headers) as base:
        backend = LiteLLMBackend(MODEL, api_base=base, api_key_env=None, timeout_s=10)
        req = echo_request().model_copy(update={"model": MODEL})
        with vcr.VCR(record_mode="all", **hooks).use_cassette(str(path)):
            asyncio.run(backend.acomplete(req))
    text = path.read_text("utf-8").lower()
    assert "secretcookie" not in text
    assert "ghp_" not in text
    assert "set-cookie" not in text

"""In-domain generation on the VM CPU model (D1201): backend switch and refusals, no server needed.

The real call is covered by ``scripts/models/tests/test_vm_llm_live.py`` (``live``) and the timed
benchmark in ``REPORT.md``; here only the plumbing that must fail closed.
"""

import socket
from pathlib import Path

import pytest
from model_selection import indomain_cli as cli
from model_selection import indomain_gen as gen
from testsupport.vm_stub import openai_stub

from pruefstand.dataset.datagen_pins import VM_DATAGEN_MODEL


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_the_vm_generator_is_the_pruefstand_pin() -> None:
    assert cli.VM_GEN_MODEL == VM_DATAGEN_MODEL
    assert gen.is_vm(cli.VM_GEN_MODEL)
    assert not gen.is_vm(cli.GITHUB_GEN_MODEL)


def test_the_default_generator_follows_the_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PRUEFSTAND_DATAGEN_BACKEND", raising=False)
    assert cli.default_gen_model() == cli.VM_GEN_MODEL
    monkeypatch.setenv("PRUEFSTAND_DATAGEN_BACKEND", "github")
    assert cli.default_gen_model() == cli.GITHUB_GEN_MODEL


def test_vm_and_github_answers_never_share_a_cache_entry() -> None:
    a = gen.cache_key(cli.VM_GEN_MODEL, "indomain_gen_v1", "gii-bgb-622")
    assert a != gen.cache_key(cli.GITHUB_GEN_MODEL, "indomain_gen_v1", "gii-bgb-622")


def test_a_vm_call_without_url_or_server_fails_closed() -> None:
    with pytest.raises(gen.GenError, match=r"vm_llm\.sh start"):
        gen.call_vm(cli.VM_GEN_MODEL, "Frage?", None)
    url = f"http://127.0.0.1:{_closed_port()}/v1"
    with pytest.raises(gen.GenError, match="VM model call failed"):
        gen.call_vm(cli.VM_GEN_MODEL, "Frage?", url, timeout_s=2.0)


def test_a_failed_vm_call_caches_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(gen, "CACHE", tmp_path)
    url = f"http://127.0.0.1:{_closed_port()}/v1"
    with pytest.raises(gen.GenError):
        gen.ask("", cli.VM_GEN_MODEL, "indomain_gen_v1", "gii-bgb-622", "Frage?", base_url=url)
    assert list(tmp_path.iterdir()) == []


def test_generate_refuses_a_server_that_serves_another_model() -> None:
    with (
        openai_stub(["qwen2.5-0.5b-instruct"]) as (url, state),
        pytest.raises(gen.GenError, match="not ministral-3-14b-instruct-2512"),
    ):
        cli.vm_check(cli.VM_GEN_MODEL, url)
    assert state.bodies == []  # nothing was generated (and nothing cached under the pin)


def test_the_generation_call_sends_the_json_schema_and_retries_sample(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(gen, "CACHE", tmp_path)
    with openai_stub(["ministral-3-14b-instruct-2512"]) as (url, state):
        gen.ask("", cli.VM_GEN_MODEL, "indomain_gen_v1", "gii-bgb-622", "Frage?", base_url=url)
        gen.ask("", cli.VM_GEN_MODEL, "indomain_gen_v1", "gii-bgb-622#retry1", "Frage?",
                base_url=url, attempt=1)  # fmt: skip
        gen.ask("", cli.VM_GEN_MODEL, "indomain_check_v1", "gii-bgb-622", "Prüfe?", base_url=url)
    first, retry1, check = state.bodies
    assert first["response_format"]["json_schema"]["schema"] == gen.GEN_SCHEMA
    assert (first["temperature"], first["seed"]) == (0.0, 42)
    assert (retry1["temperature"], retry1["seed"]) == (gen.RETRY_TEMPERATURE, 43)
    assert retry1["response_format"]["type"] == "json_schema"
    assert "response_format" not in check

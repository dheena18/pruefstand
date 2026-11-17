"""``indomain_cli generate`` / ``check`` on the VM model (D1201): served-alias check first, errors.

Plumbing only, against the loopback stub (``testsupport.vm_stub``); real answers are in the
recorded retry fixture and the live checks.
"""

import json
from pathlib import Path

import pytest
from model_selection import indomain_cli as cli
from model_selection import indomain_data as data
from model_selection import indomain_gen as gen
from testsupport.vm_stub import openai_stub

FIXTURE = Path(__file__).parent / "fixtures" / "indomain_retry_14b.json"
PASSAGE = data.Passage(**json.loads(FIXTURE.read_text(encoding="utf-8"))["items"][0]["passage"])
ALIAS = "ministral-3-14b-instruct-2512"


@pytest.fixture(autouse=True)
def _vm(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("PRUEFSTAND_DATAGEN_BACKEND", raising=False)
    monkeypatch.setattr(gen, "CACHE", tmp_path / "cache")


def _no_passages() -> dict[str, data.Passage]:
    pytest.fail("the served model must be checked before any passage is loaded")


@pytest.mark.parametrize(
    "argv",
    [
        ["generate", "--max-calls", "1"],
        ["check", "--model", cli.VM_GEN_MODEL, "--gen-model", "openai/gpt-4.1-mini"],
    ],
)
def test_another_served_model_stops_the_command_before_any_call(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    monkeypatch.setattr(cli, "load_passages", _no_passages)
    with openai_stub(["qwen2.5-0.5b-instruct"]) as (url, state):
        monkeypatch.setenv("PRUEFSTAND_DATAGEN_BASE_URL", url)
        assert cli.main(argv) == 1
    assert state.bodies == []
    assert f"not {ALIAS}" in capsys.readouterr().err


def test_a_non_quota_error_prints_the_summary_and_exits_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "load_passages", lambda: {PASSAGE.id: PASSAGE})
    monkeypatch.setattr(cli, "load_plan", lambda: [PASSAGE.id])
    with openai_stub([ALIAS], answer_model="some-other-model") as (url, state):
        monkeypatch.setenv("PRUEFSTAND_DATAGEN_BASE_URL", url)
        assert cli.main(["generate", "--max-calls", "3"]) == 1
    err = capsys.readouterr().err
    assert len(state.bodies) == 1
    assert "stopped: the VM server answered as 'some-other-model'" in err
    assert "0 new calls (0 retries), 0 items exhausted" in err
    assert not gen.CACHE.exists() or list(gen.CACHE.iterdir()) == []

"""``scripts/contamination_probe.py``: report-only closed-book probe (T4.6 S7)."""

import json
from pathlib import Path

import numpy as np
import pytest
from contamination_probe import build_report, known_by_model, main, probeable
from testsupport.attack_support import registry_3_tenants
from testsupport.gpu_files import SHIPPED_CATALOGUE, SHIPPED_ENDPOINTS
from testsupport.loopback_script import serve_script

from pruefstand.attacks.rotation import RetiredCanary, load_retired, retire, rotate_canaries

MODEL = ("--model", "ollama/gemma3:12b", "--family", "gemma")


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRUEFSTAND_GPU_CATALOGUE", str(SHIPPED_CATALOGUE))
    monkeypatch.setenv("PRUEFSTAND_GPU_ENDPOINTS", str(SHIPPED_ENDPOINTS))
    monkeypatch.setenv("PRUEFSTAND_LOCK_HELD", "1")


def retired_file(tmp_path: Path) -> Path:
    path = tmp_path / "retired.json"
    _, gone = rotate_canaries(registry_3_tenants(), "v2", np.random.default_rng(1))
    retire(path, gone, retired_in="v1")
    return path


def test_only_semantic_canaries_with_question_and_pattern_are_probed(tmp_path: Path) -> None:
    path = retired_file(tmp_path)
    entries = probeable(load_retired(path))
    assert len(entries) == 3
    assert all(e.fact and e.probe_question and e.forbidden_answer for e in entries)


def test_a_model_that_states_the_fact_is_known_and_one_that_does_not_is_not(tmp_path: Path) -> None:
    path = retired_file(tmp_path)
    km = next(e for e in probeable(load_retired(path)) if e.tenant == "kanzlei_mueller")
    assert known_by_model("Die Frist beträgt 47 Tage.", km)
    assert not known_by_model("Unbekannt", km)
    assert not known_by_model("Das sind 147 Tage.", km)


def test_report_holds_counts_and_flags_but_no_answer_text() -> None:
    entry = RetiredCanary(token="47 Tage", tenant="kanzlei_mueller", fact="x", retired_in="v1")  # noqa: S106
    report = build_report("ollama/m", "2026-11-03", [entry, entry], [True, False])
    assert report["n_probed"] == 2
    assert report["n_known"] == 1
    assert report["report_only"] is True
    results = report["results"]
    assert isinstance(results, list)
    assert [r["known"] for r in results] == [True, False]


def test_nothing_retired_writes_an_empty_report_without_calling_a_model(tmp_path: Path) -> None:
    retired = tmp_path / "retired.json"
    retired.write_text("[]\n", encoding="utf-8")
    out = tmp_path / "out"
    args = [*MODEL, "--retired", str(retired), "--out-dir", str(out), "--date", "2026-11-03"]
    assert main(args) == 0
    report = json.loads((out / "contamination_2026-11-03.json").read_text("utf-8"))
    assert (report["n_probed"], report["n_known"]) == (0, 0)


def test_external_providers_and_a_missing_lock_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = retired_file(tmp_path)
    base = ["--retired", str(path), "--out-dir", str(tmp_path / "out")]
    assert main(["--model", "github/openai/gpt-4.1-mini", "--family", "openai", *base]) == 2
    assert "external provider" in capsys.readouterr().err
    monkeypatch.delenv("PRUEFSTAND_LOCK_HELD")
    assert main([*MODEL, *base]) == 2
    assert "pruefstand-lock" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_a_run_asks_each_question_closed_book_and_reports_hits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = retired_file(tmp_path)
    out = tmp_path / "out"
    with serve_script(content="Unbekannt") as (origin, state):
        monkeypatch.setenv("OLLAMA_GPU1_URL", origin)
        assert (
            main([*MODEL, "--retired", str(path), "--out-dir", str(out), "--date", "2026-11-03"])
            == 0
        )
        chats = [x for x in state.seen if x.path == "/api/chat"]
    assert len(chats) == 3
    for seen in chats:
        messages = seen.body["messages"]
        assert isinstance(messages, list)
        assert [m["role"] for m in messages] == ["system", "user"]
        assert messages[1]["content"].endswith("?")
        assert seen.body["think"] is False
    report = json.loads((out / "contamination_2026-11-03.json").read_text("utf-8"))
    assert (report["n_probed"], report["n_known"]) == (3, 0)
    assert "Unbekannt" not in json.dumps(report)

"""T5.4e step A: the VM CPU judge in the RQ2 config, backend, concurrency, MEMERAG routing."""

import socket
from pathlib import Path

import pytest
from rq2.binarise import check_route, is_local
from rq2.rq2_config import REPO, SetEntry, load_config, load_items
from rq2.run_judges import is_vm, judge_concurrency, make_judge
from rq2.vm_arm import VM_JUDGE, cassette_items

from pruefstand.core.errors import ConfigError
from pruefstand.llm.recorder import CallRecorder

CFG = load_config(REPO / "experiments/rq2/configs/rq2_judges.yaml")
MEMERAG = "data/derived/memerag_de/faithfulness_memerag.jsonl"


def _closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_the_vm_judge_is_the_enabled_arm_c_and_the_datagen_family() -> None:
    entry = next(j for j in CFG.judges if j.id == VM_JUDGE)
    assert (entry.family, entry.arm, entry.enabled) == ("mistral", "c", True)
    assert not any(j.enabled for j in CFG.judges if j.id.startswith("github/"))  # retired, D1202
    assert (
        CFG.datagen_family == "mistral"
    )  # the VM Ministral writes the public datagen text (D1201)


def test_the_vm_model_is_local_so_memerag_may_be_judged_there() -> None:
    assert is_local(VM_JUDGE)
    check_route(VM_JUDGE, "memerag", MEMERAG, local_only=True)
    with pytest.raises(ConfigError, match="local judges only"):
        check_route("github/openai/gpt-4.1-mini", "memerag", MEMERAG, local_only=True)


def test_the_vm_judge_runs_one_call_at_a_time() -> None:
    entries = {j.id: j for j in CFG.judges}
    assert is_vm(VM_JUDGE)
    assert not is_vm("ollama/gemma3:12b")
    assert judge_concurrency(CFG, entries[VM_JUDGE]) == 1
    assert judge_concurrency(CFG, entries["ollama/gemma3:12b"]) == CFG.concurrency


def test_the_vm_judge_is_refused_when_nothing_serves_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRUEFSTAND_DATAGEN_BASE_URL", f"http://127.0.0.1:{_closed_port()}/v1")
    entry = next(j for j in CFG.judges if j.id == VM_JUDGE)
    with pytest.raises(ConfigError):
        make_judge(entry, None, CallRecorder())


def test_cassette_items_never_hold_memerag() -> None:
    items = cassette_items(CFG)
    assert len(items) == 3
    assert all(item.source != "memerag" and item.calib_split == "test" for item in items)


def test_cassette_items_drop_a_local_only_set_even_when_it_comes_first(tmp_path: Path) -> None:
    """Licence guard (MEMERAG, CC BY-NC 4.0, never redistributed): no local-only text in a cassette.

    MEMERAG data is absent in CI, so a tmp local-only set stands in for it: it is listed FIRST,
    so without the filter its items would be the first three cassette items.
    """
    real = load_items(CFG.set_named("correctness"), "test")[:5]
    mem = [i.model_copy(update={"item_id": f"mem-{i.item_id}", "source": "memerag"}) for i in real]
    files = {"memerag": mem, "correctness": real}
    for name, items in files.items():
        lines = "".join(i.model_dump_json() + "\n" for i in items)
        (tmp_path / f"{name}.jsonl").write_text(lines, encoding="utf-8")
    sets = [
        SetEntry(
            name="memerag", path=str(tmp_path / "memerag.jsonl"), origin="human", local_only=True
        ),
        SetEntry(
            name="correctness", path=str(tmp_path / "correctness.jsonl"), origin="construction"
        ),
    ]
    cfg = CFG.model_copy(update={"sets": sets})
    picked = cassette_items(cfg)
    assert len(picked) == 3
    assert not any(i.item_id.startswith("mem-") or i.source == "memerag" for i in picked)

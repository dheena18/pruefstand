"""``scripts/generate_private_docs.py``: model check, plan, output check, resume (T2.6 S2)."""

from pathlib import Path

import pytest
from generate_private_docs import main
from private_doc_plan import (
    DraftRejectedError,
    check_datagen_model,
    check_output,
    default_model,
    plan_documents,
)
from testsupport.gpu_files import SHIPPED_CATALOGUE, SHIPPED_ENDPOINTS
from testsupport.loopback_script import ScriptState, Seen, serve_script

from pruefstand.core.config import ModelRef
from pruefstand.core.errors import ConfigError

TENANT = "kanzlei_mueller"
WORDS = "Die Kanzlei hat die Unterlagen geprüft und mit der Leitung besprochen. " * 14


ENGLISH = "The firm has checked the documents and discussed them with the management. " * 14


def english(fact: str) -> str:
    return f"# Memo\n\n{ENGLISH}\n\n{fact}\n\n{ENGLISH}\n[ENDE]"


def draft(fact: str, end: str = "\n[ENDE]") -> str:
    return f"# Aktennotiz zum Mandat\n\n{WORDS}\n\n{fact}\n\n{WORDS}{end}"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRUEFSTAND_GPU_CATALOGUE", str(SHIPPED_CATALOGUE))
    monkeypatch.setenv("PRUEFSTAND_GPU_ENDPOINTS", str(SHIPPED_ENDPOINTS))
    monkeypatch.setenv("PRUEFSTAND_LOCK_HELD", "1")


def test_the_judge_family_is_accepted() -> None:
    check_datagen_model(ModelRef(id="ollama/gemma3:12b", family="gemma"))
    check_datagen_model(ModelRef(id="openai_compatible_local/phi-3-mini", family="phi"))


@pytest.mark.parametrize(
    ("model", "family", "needle"),
    [
        ("ollama/qwen3.8:27b-q8_0", "qwen", "generator family"),
        ("ollama/gemma3:12b", "Qwen", "generator family"),
        ("ollama/qwen3:8b", "gemma", "generator family"),
        ("openai_compatible_local/Qwen2.5-1.5B", "other", "generator family"),
        ("github/openai/gpt-4.1-mini", "openai", "external provider"),
        ("mistral/mistral-small", "mistral", "external provider"),
    ],
)
def test_qwen_and_external_models_are_refused(model: str, family: str, needle: str) -> None:
    with pytest.raises(ConfigError, match=needle):
        check_datagen_model(ModelRef(id=model, family=family))


def test_the_default_model_is_the_catalogue_judge() -> None:
    ref = default_model(SHIPPED_CATALOGUE)
    assert ref.id.startswith("ollama/")
    assert ref.family == "gemma"
    check_datagen_model(ref)


def test_the_plan_is_seeded_and_every_fact_is_distinct() -> None:
    first = plan_documents(TENANT, 8, seed=7)
    assert first == plan_documents(TENANT, 8, seed=7)
    assert first != plan_documents(TENANT, 8, seed=8)
    assert len({p.front.doc_id for p in first}) == 8
    assert len({p.fact.value for p in first}) == 8
    with pytest.raises(ConfigError, match="at most"):
        plan_documents(TENANT, 13, seed=7)


def test_check_output_cleans_a_valid_draft_and_rejects_the_rest() -> None:
    plan = plan_documents(TENANT, 1, seed=7)[0]
    fact = plan.front.semantic_fact
    body = check_output(draft(fact), plan)
    assert body.startswith("# ")
    assert "[ENDE]" not in body
    assert body.count(fact) == 1
    for text, reason in [
        (draft(fact, end=""), "end marker"),
        (draft("Ohne den Satz."), "exactly once"),
        (draft(fact + "\n\n" + fact), "exactly once"),
        (draft(fact + " Ref.: CANARY-KM-123456"), "CANARY"),
        ("# Kurz\n\n" + fact + "\n[ENDE]", "words"),
        (draft(fact).replace("# Aktennotiz zum Mandat\n\n", ""), "heading"),
        (english(fact), "German"),
    ]:
        with pytest.raises(DraftRejectedError, match=reason):
            check_output(text, plan)


def chats(state: ScriptState) -> list[Seen]:
    return [x for x in state.seen if x.path == "/api/chat"]


def run(tmp_path: Path, *extra: str) -> int:
    drafts = tmp_path / "drafts"
    return main(["--tenant", TENANT, "--n", "1", "--seed", "7", "--drafts", str(drafts), *extra])


def test_a_run_writes_one_draft_and_a_second_run_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = plan_documents(TENANT, 1, seed=7)[0]
    with serve_script(content=draft(plan.front.semantic_fact)) as (origin, state):
        monkeypatch.setenv("OLLAMA_GPU1_URL", origin)
        assert run(tmp_path) == 0
        assert len(chats(state)) == 1
        assert run(tmp_path) == 0
        assert len(chats(state)) == 1
    (path,) = (tmp_path / "drafts" / TENANT).glob("*.md")
    text = path.read_text("utf-8")
    assert text.startswith("---\n")
    assert plan.front.semantic_fact in text
    assert "CANARY" not in text
    (seen,) = chats(state)
    assert seen.body["model"] == "gemma3:12b"
    assert seen.body["think"] is False
    messages = seen.body["messages"]
    assert isinstance(messages, list)
    assert messages[0]["role"] == "system"
    assert plan.front.semantic_fact in messages[1]["content"]


def test_a_bad_answer_is_retried_then_reported_and_no_draft_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with serve_script(content=draft("Ohne den Satz.")) as (origin, state):
        monkeypatch.setenv("OLLAMA_GPU1_URL", origin)
        assert run(tmp_path, "--attempts", "2") == 1
        assert len(chats(state)) == 2
    assert not list((tmp_path / "drafts").rglob("*.md"))


def test_refusals_happen_before_any_network_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with serve_script() as (origin, state):
        monkeypatch.setenv("OLLAMA_GPU1_URL", origin)
        assert run(tmp_path, "--model", "github/openai/gpt-4.1-mini", "--family", "openai") == 2
        assert run(tmp_path, "--model", "ollama/qwen3.8:27b-q8_0", "--family", "qwen") == 2
        monkeypatch.delenv("PRUEFSTAND_LOCK_HELD")
        assert run(tmp_path) == 2
        assert len(chats(state)) == 0

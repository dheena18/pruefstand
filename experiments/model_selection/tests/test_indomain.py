"""T3.1b in-domain dev set: rules, planning, assembly, token and cache handling (no network)."""

import json
from pathlib import Path

import pytest
from model_selection import indomain_cli as cli
from model_selection import indomain_data as data
from model_selection import indomain_gen as gen
from model_selection.bench_cases import prompt_text

PASSAGE = (
    "(1) Die Kündigungsfrist beträgt bei einer Kündigung durch den Arbeitgeber, wenn das "
    "Arbeitsverhältnis in dem Betrieb oder Unternehmen zwei Jahre bestanden hat, einen Monat "
    "zum Ende eines Kalendermonats. (2) Die Kündigung des Arbeitsverhältnisses bedarf zu ihrer "
    "Wirksamkeit der Schriftform; die elektronische Form ist ausgeschlossen. " * 2
)
SPAN = "einen Monat zum Ende eines Kalendermonats"
GOOD = {
    "question": "Welche Kündigungsfrist gilt nach zwei Jahren Betriebszugehörigkeit?",
    "evidence_span": SPAN + ". (2) Die Kündigung des Arbeitsverhältnisses bedarf",
    "reference_answer": "Der Arbeitgeber muss einen Monat zum Ende eines Kalendermonats einhalten.",
}


def test_valid_item_gets_offsets_into_the_passage() -> None:
    item, why = data.validate_item(GOOD, PASSAGE)
    assert item is not None
    assert why == ""
    assert PASSAGE[item["evidence_start"] : item["evidence_end"]] == item["evidence_span"]


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"question": "Wie lang ist die Kündigungsfrist nach zwei Jahren"}, "not_a_question"),
        ({"question": "Wie lang?"}, "question_length"),
        ({"question": "What is the notice period for the employer after two years?"}, "not_german"),
        (
            {"question": "Was steht im Text über die Kündigungsfrist des Arbeitgebers?"},
            "meta_reference",
        ),
        (
            {"evidence_span": "Dieser Satz steht nirgends im Abschnitt, ist aber lang."},
            "span_not_verbatim",
        ),
        ({"evidence_span": "einen Monat"}, "span_length"),
        ({"reference_answer": "Ein Monat"}, "answer_length"),
    ],
)
def test_item_rules_reject_with_a_reason(change: dict[str, str], reason: str) -> None:
    item, why = data.validate_item({**GOOD, **change}, PASSAGE)
    assert item is None
    assert why == reason


def _passages() -> list[data.Passage]:
    rows = []
    for law in ("bgb", "hgb", "kschg"):
        for i in range(30):
            rows.append(
                data.Passage(f"gii-{law}-{i}", law.upper(), "", "", f"{law} {i} " + "Satz. " * 80)
            )
    return rows


def test_plan_is_reproducible_spread_and_respects_exclusions() -> None:
    ps = _passages()
    excluded = {"gii-bgb-1", "gii-hgb-2"}
    plan = data.plan_passages(ps, 30, seed=5, excluded=excluded)
    assert plan == data.plan_passages(list(reversed(ps)), 30, seed=5, excluded=excluded)
    assert plan != data.plan_passages(ps, 30, seed=6, excluded=excluded)
    assert len(plan) == len(set(plan)) == 30
    assert not excluded & set(plan)
    assert {p.split("-")[1] for p in plan[:3]} == {"bgb", "hgb", "kschg"}  # round-robin
    assert all(sum(p.startswith(f"gii-{k}-") for p in plan) == 10 for k in ("bgb", "hgb", "kschg"))


def test_plan_skips_short_long_and_duplicate_text() -> None:
    long_text = "x" * 400
    ps = [
        data.Passage("gii-a-1", "A", "", "", "kurz"),
        data.Passage("gii-a-2", "A", "", "", "y" * 2000),
        data.Passage("gii-a-3", "A", "", "", long_text),
        data.Passage("gii-b-3", "B", "", "", long_text),
    ]
    assert data.plan_passages(ps, 5) == ["gii-a-3"]


def test_slice_norms_are_excluded_from_the_committed_plan() -> None:
    plan = set(json.loads(data.SOURCES_PATH.read_text(encoding="utf-8"))["plan_order"])
    assert "gii-bgb-622" in data.slice_doc_ids()
    assert not plan & data.slice_doc_ids()


def _assembly_inputs(
    n: int = 36,
) -> tuple[list[str], dict[str, data.Passage], dict[str, data.Item], dict[str, dict[str, object]]]:
    plan = [f"gii-bgb-{i}" for i in range(n)]
    passages = {p: data.Passage(p, "BGB", f"§ {i} BGB", "T", PASSAGE) for i, p in enumerate(plan)}
    good, _ = data.validate_item(GOOD, PASSAGE)
    assert good is not None
    items = dict.fromkeys(plan, good)
    ok = {"answerable": True, "german": True, "single_passage": True, "reason": "ok"}
    bad = {**ok, "answerable": False}
    verdicts = {p: (bad if i in (3, 17) else ok) for i, p in enumerate(plan[: data.N_CHECK])}
    return plan, passages, items, verdicts


def test_assemble_drops_failed_checks_and_fills_from_the_reserve() -> None:
    plan, passages, items, verdicts = _assembly_inputs()
    records, stats = data.assemble(plan, passages, items, verdicts, n=34)
    ids = [r["gold_passage_id"] for r in records]
    assert len(records) == 34
    assert "gii-bgb-3" not in ids
    assert "gii-bgb-17" not in ids
    assert ids[-1] == "gii-bgb-35"
    assert stats["dropped_check"] == 2
    assert stats["checked"] == 30
    assert all(r["dev_only"] is True for r in records)
    assert [r["id"] for r in records[:2]] == ["idev-001", "idev-002"]
    assert records[0]["checked"]["answerable"] is True
    assert records[-1]["checked"] is None


def test_assemble_requires_a_verdict_for_every_checked_item() -> None:
    plan, passages, items, verdicts = _assembly_inputs()
    del verdicts["gii-bgb-5"]
    with pytest.raises(ValueError, match="gii-bgb-5"):
        data.assemble(plan, passages, items, verdicts, n=10)


def test_missing_items_are_skipped_and_counted() -> None:
    plan, passages, items, verdicts = _assembly_inputs()
    del items["gii-bgb-31"]
    records, stats = data.assemble(plan, passages, items, verdicts, n=34)
    assert stats["dropped_no_item"] == 1
    assert len(records) == 33


def test_checker_must_be_another_provider_family() -> None:
    assert data.family_of("openai/gpt-4.1-mini") == "openai"
    assert data.family_of("meta/Llama-3.3-70B-Instruct") == "meta"
    code = cli.main(["check", "--model", "openai/gpt-4.1", "--gen-model", "openai/gpt-4.1-mini"])
    assert code == cli.EXIT_USAGE


def test_verdict_needs_three_yes() -> None:
    assert data.verdict_passes({"answerable": True, "german": True, "single_passage": True})
    assert not data.verdict_passes({"answerable": True, "german": True})
    assert not data.verdict_passes({"answerable": True, "german": "true", "single_passage": True})


def test_token_comes_from_env_or_a_single_env_file_line(tmp_path: Path) -> None:
    secret = "ghp_" + "x" * 20  # reason: dummy value for the parser
    assert gen.read_token({gen.TOKEN_VAR: secret}) == secret
    env_file = tmp_path / ".env"
    env_file.write_text(f'OTHER=1\nGITHUB_TOKEN=wrong\n{gen.TOKEN_VAR}="{secret}"\n', "utf-8")
    assert gen.read_token({}, env_file) == secret
    with pytest.raises(gen.GenError) as err:
        gen.read_token({}, tmp_path / "missing")
    assert secret not in str(err.value)
    assert gen.TOKEN_VAR in str(err.value)


def test_json_object_is_found_in_fenced_answers() -> None:
    assert gen.parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    for bad in ("kein JSON", "[1, 2]", "{kaputt"):
        with pytest.raises(gen.GenError):
            gen.parse_json_object(bad)


def test_cache_key_depends_on_model_prompt_and_passage() -> None:
    k = gen.cache_key("openai/a", "indomain_gen_v1", "gii-bgb-1")
    assert k == gen.cache_key("openai/a", "indomain_gen_v1", "gii-bgb-1")
    assert (
        len(
            {
                k,
                gen.cache_key("openai/b", "indomain_gen_v1", "gii-bgb-1"),
                gen.cache_key("openai/a", "indomain_gen_v2", "gii-bgb-1"),
                gen.cache_key("openai/a", "indomain_gen_v1", "gii-bgb-2"),
            }
        )
        == 4
    )


def test_prompts_fill_and_ask_for_json_with_every_field() -> None:
    g = prompt_text(data.GEN_PROMPT).format(
        law="§ 622 BGB", title="Kündigungsfristen", passage=PASSAGE
    )
    c = prompt_text(data.CHECK_PROMPT).format(question="F?", reference_answer="A.", passage=PASSAGE)
    for field in ("question", "evidence_span", "reference_answer"):
        assert f'"{field}"' in g
    for field in ("answerable", "german", "single_passage"):
        assert f'"{field}"' in c
    assert "{law}" not in g
    assert "{passage}" not in c


def test_card_is_filled_from_the_records() -> None:
    plan, passages, items, verdicts = _assembly_inputs()
    records, stats = data.assemble(plan, passages, items, verdicts, n=34)
    card = data.render_card(records, stats, "openai/gpt-4.1-mini", "meta/Llama-3.3-70B-Instruct")
    assert "34 German questions" in card
    assert "| BGB | 34 |" in card
    assert "2 dropped" in card
    assert "{" not in card
    assert "}" not in card


def test_committed_sources_file_is_a_valid_exclusion_list() -> None:
    doc = json.loads(data.SOURCES_PATH.read_text(encoding="utf-8"))
    ids = data.load_sources()
    assert doc["schema"] == 1
    assert doc["dev_only"] is True
    assert doc["status"] in ("planned", "final")
    assert len(ids) == data.N_ITEMS + data.N_RESERVE == len(doc["plan_order"])
    assert set(doc["used_passage_ids"]) <= ids
    assert all(i.startswith("gii-") for i in ids)
    assert set(doc["pins"]) == set(cli.source_ids())


def test_committed_dev_set_matches_its_rules_when_present() -> None:
    if not data.DEV_PATH.is_file():
        pytest.skip("indomain_dev.jsonl is generated through GitHub Models (not yet committed)")
    rows = [json.loads(ln) for ln in data.DEV_PATH.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == data.N_ITEMS
    assert all(r["dev_only"] is True for r in rows)
    assert {r["gold_passage_id"] for r in rows} == set(
        json.loads(data.SOURCES_PATH.read_text(encoding="utf-8"))["used_passage_ids"]
    )
    for r in rows:
        assert data.validate_item(r, r["passage"])[0] is not None
        assert data.family_of(r["generator_model"]) != data.family_of(r["checker_model"])
    checked = [r["checked"] for r in rows if r["checked"] is not None]
    assert checked
    assert all(data.verdict_passes(v) for v in checked)


@pytest.mark.parametrize("step", ["generate", "check"])
def test_calls_can_be_paced_for_the_free_tier(
    step: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as stop:
        cli.main([step, "--help"])
    assert stop.value.code == 0
    assert "--pause-s" in capsys.readouterr().out

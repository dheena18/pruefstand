"""Deterministic overrides, family and privacy rules of the model review (T4.7a)."""

import pytest
from pydantic import ValidationError
from testsupport.qa_support import chunk
from testsupport.review_support import REVIEWER

from pruefstand.core.config import DatasetBuildConfig, ModelRef
from pruefstand.core.enums import Category, Difficulty, Lang, Split
from pruefstand.core.errors import ConfigError
from pruefstand.core.models.dataset import ModelVerdict, ReviewChecks
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.model_review import (
    _request,
    _tenant_norms,
    check_reviewer,
    check_reviewer_for_case,
    citation_matches,
    finalise,
    lost_facts,
    source_chunks_of,
)
from pruefstand.perturb.rewriter import private_text

GEMMA = ModelRef(id=REVIEWER, family="gemma")
QWEN = ModelRef(id="ollama/qwen3.8:27b-q8_0", family="qwen")
GPT = ModelRef(id="github/openai/gpt-4.1-mini", family="gpt")
LLAMA = ModelRef(id="ollama/llama3.3:70b", family="llama")
ANSWER = "Nach zwei Jahren beträgt die Kündigungsfrist einen Monat zum Ende eines Kalendermonats."
QUESTION = "Wie lange ist die Kündigungsfrist, wenn ich seit zwei Jahren im Betrieb bin?"
GOOD = ReviewChecks(
    natural=True, correct=True, citation_exact=True,
    perturbation_equivalent=True, unanswerable_ok=True,
)  # fmt: skip


def _case(
    *, tenant: str = "shared_public", citations: tuple[str, ...] = ("§ 622 Abs. 2 BGB",)
) -> TestCase:
    return TestCase.model_validate(
        {
            "id": "qa-0001", "base_id": "qa-0001", "cluster_id": "gii-bgb-622", "tenant": tenant,
            "lang": Lang.DE, "question": QUESTION, "reference_answer": ANSWER,
            "gold_doc_ids": ("gii-bgb-622",), "gold_citations": citations,
            "evidence_span": "einen Monat zum Ende eines Kalendermonats",
            "category": Category.FACTUAL, "difficulty": Difficulty.EASY, "split": Split.CORE,
            "source": "generated", "license_config": "laws_eurlex", "corpus_version": "slice",
            "generation_prompt_version": "qa_factual_de_v1",
        }
    )  # fmt: skip


def _verdict(kind: str, **fields: str | None) -> ModelVerdict:
    return ModelVerdict(reason="Kurze Begründung.", checks=GOOD, verdict=kind, **fields)  # type: ignore[arg-type]


def test_ok_with_a_citation_that_names_another_paragraph_is_rejected() -> None:
    item = finalise(_case(), [chunk("gii-bgb-623#0")], _verdict("ok"), model=REVIEWER)
    assert item.verdict == "reject"
    assert "citation_mismatch" in item.reasons
    assert item.model_verdict == "ok"


def test_ok_with_the_matching_citation_stays_ok() -> None:
    item = finalise(_case(), [chunk("gii-bgb-622#1")], _verdict("ok"), model=REVIEWER)
    assert (item.verdict, item.reasons) == ("ok", ())


def test_a_case_without_a_source_chunk_is_rejected() -> None:
    item = finalise(_case(), [], _verdict("ok"), model=REVIEWER)
    assert item.reasons == ("chunk_missing",)


def test_a_valid_question_only_fix_is_kept() -> None:
    fixed = "Wie viel Zeit muss mir mein Arbeitgeber geben, wenn ich schon zwei Jahre dabei bin?"
    item = finalise(
        _case(), [chunk("gii-bgb-622#1")], _verdict("fix", fixed_question=fixed), model=REVIEWER
    )
    assert (item.verdict, item.fixed_question, item.fixed_answer) == ("fix", fixed, None)


def test_a_fix_that_drops_a_duration_of_the_source_is_rejected() -> None:
    lossy = "Nach zwei Jahren beträgt die Kündigungsfrist vier Wochen."
    verdict = _verdict(
        "fix", fixed_question="Wie lange darf mir gekündigt werden?", fixed_answer=lossy
    )
    may_rewrite = finalise(
        _case(), [chunk("gii-bgb-622#1")], verdict, model=REVIEWER, reject_only=False
    )
    assert may_rewrite.verdict == "reject"
    assert "fix_lost_fact" in may_rewrite.reasons
    reject_only = finalise(_case(), [chunk("gii-bgb-622#1")], verdict, model=REVIEWER)
    assert reject_only.reasons == ("reference_rewrite_forbidden",)


def test_a_fix_that_keeps_every_fact_may_rewrite_when_allowed() -> None:
    kept = "Nach zwei Jahren beträgt sie dann einen Monat zum Ende eines Kalendermonats."
    verdict = _verdict(
        "fix", fixed_question="Wie lange ist die Frist nach zwei Jahren?", fixed_answer=kept
    )
    item = finalise(_case(), [chunk("gii-bgb-622#1")], verdict, model=REVIEWER, reject_only=False)
    assert (item.verdict, item.fixed_answer) == ("fix", kept)


def test_a_fixed_question_that_copies_the_source_is_rejected() -> None:
    source = chunk("gii-bgb-622#1")
    copied = (
        "Für eine Kündigung durch den Arbeitgeber beträgt die Kündigungsfrist, "
        "wenn das Arbeitsverhältnis in dem Betrieb"
    )
    item = finalise(_case(), [source], _verdict("fix", fixed_question=copied), model=REVIEWER)
    assert item.verdict == "reject"
    assert item.reasons == ("fix_copies_source",)


def test_a_fix_that_changes_nothing_or_gives_no_text_is_rejected() -> None:
    same = finalise(
        _case(), [chunk("gii-bgb-622#1")], _verdict("fix", fixed_question=QUESTION), model=REVIEWER
    )
    assert same.reasons == ("fix_unchanged",)
    empty = finalise(_case(), [chunk("gii-bgb-622#1")], _verdict("fix"), model=REVIEWER)
    assert empty.reasons == ("fix_without_text",)


@pytest.mark.parametrize(
    ("gold", "key", "expected"),
    [
        ("§ 622 Abs. 2 BGB", "§ 622 BGB", True),
        ("§ 622 BGB", "§ 622 BGB", True),
        ("§ 622 Abs. 2 BGB", "§ 623 BGB", False),
        ("§ 622 Abs. 2 BGB", "§ 622 Abs. 3 BGB", False),
        ("§ 622 BGB", "§ 622 KSchG", False),
        ("Art. 6 DSGVO", "§ 6 DSGVO", False),
        ("keine Angabe", "§ 622 BGB", False),
        ("§ 622 BGB", None, False),
    ],
)
def test_citation_matching(gold: str, key: str | None, *, expected: bool) -> None:
    assert citation_matches(gold, key) is expected


def test_lost_facts_names_the_missing_duration() -> None:
    text = chunk("gii-bgb-622#1").text
    assert lost_facts(ANSWER, "Es sind vier Wochen.", text) == ["zwei Jahren", "einen Monat"]
    assert lost_facts(ANSWER, ANSWER, text) == []
    assert (
        lost_facts("Sie beträgt 99 Jahre.", "Sie ist lang.", text) == []
    )  # 99 is not in the source


def test_the_source_chunk_with_the_evidence_is_preferred() -> None:
    by_doc = {
        "gii-bgb-622": [chunk("gii-bgb-622#0"), chunk("gii-bgb-622#1"), chunk("gii-bgb-622#2")]
    }
    (found,) = source_chunks_of(_case(), by_doc)
    assert found.chunk_id == "gii-bgb-622#1"
    assert source_chunks_of(_case(), {}) == []


def test_reviewer_of_the_generator_or_datagen_family_is_refused() -> None:
    check_reviewer(GEMMA, generator=QWEN, datagen=GPT)
    check_reviewer(LLAMA, generator=QWEN, datagen=GPT)
    with pytest.raises(ConfigError, match="generator family"):
        check_reviewer(QWEN, generator=QWEN, datagen=GPT)
    with pytest.raises(ConfigError, match="datagen family"):
        check_reviewer(GPT, generator=QWEN, datagen=GPT)


def _config(core_smoke: ModelRef) -> dict[str, object]:
    return {
        "name": "pruefstand-de", "dataset_version": "v1", "corpus_dir": "corpus/slice_v1",
        "models": {"datagen": GPT, "generator": QWEN},
        "review": {"reviewers": {"core_smoke": core_smoke, "full": GEMMA}},
    }  # fmt: skip


def test_the_config_accepts_the_gating_judge_family_as_a_reject_only_reviewer() -> None:
    cfg = DatasetBuildConfig.model_validate(_config(GEMMA))
    assert cfg.review is not None
    assert cfg.review.reviewers.core_smoke.family == "gemma"


@pytest.mark.parametrize("bad", [QWEN, GPT])
def test_the_config_refuses_a_reviewer_of_the_generator_or_datagen_family(bad: ModelRef) -> None:
    with pytest.raises(ValidationError, match="family"):
        DatasetBuildConfig.model_validate(_config(bad))


def test_a_private_tenant_case_never_goes_to_an_external_reviewer() -> None:
    private = _case(tenant="kanzlei_mueller")
    with pytest.raises(ConfigError, match="external reviewer"):
        check_reviewer_for_case("github/meta/Llama-3.3-70B-Instruct", private)
    check_reviewer_for_case(REVIEWER, private)
    check_reviewer_for_case("github/meta/Llama-3.3-70B-Instruct", _case())


def test_an_unanswerable_case_is_not_fixed() -> None:
    case = _case().model_copy(
        update={
            "category": Category.UNANSWERABLE, "expect_refusal": True, "reference_answer": None,
            "gold_doc_ids": (), "gold_citations": (), "evidence_span": None,
        }
    )  # fmt: skip
    verdict = _verdict("fix", fixed_question="Kann man ein Testament anfechten?")
    item = finalise(case, [], verdict, model=REVIEWER)
    assert (item.verdict, item.reasons) == ("reject", ("fix_unanswerable",))


def test_a_private_tenant_request_carries_the_private_prompt_id() -> None:
    case = _case(tenant="kanzlei_mueller")
    with private_text(private=True):
        private = _request(case, "Text", "", REVIEWER)
    public = _request(_case(), "Text", "", REVIEWER)
    assert private.prompt_id.startswith("datagen.private_docs.")
    assert public.prompt_id == "review_item_de"


def test_the_prompt_of_an_unanswerable_case_does_not_grow_with_the_corpus() -> None:
    base = chunk("gii-bgb-622#1")
    laws = ["BGB", "KSchG", "ArbZG", "DSGVO", "BDSG", "HGB", "ZPO", "AGG", "BetrVG", "TzBfG"]
    big = [
        base.model_copy(update={"chunk_id": f"x-{n}#0", "citation_key": f"§ {n} {laws[n % 10]}"})
        for n in range(1, 4001)
    ]
    norms = _tenant_norms(big)
    assert len(norms[base.tenant]) < 200
    case = _case().model_copy(
        update={"category": Category.UNANSWERABLE, "expect_refusal": True, "reference_answer": None}
    )
    request = _request(case, norms[base.tenant], "", REVIEWER)
    assert sum(len(m.content) for m in request.messages) < 3000


def test_an_answer_with_a_duration_the_source_lacks_is_rejected() -> None:
    wrong = _case().model_copy(update={"reference_answer": "Elf Monate zum Quartalsende."})
    item = finalise(wrong, [chunk("gii-bgb-622#1")], _verdict("ok"), model=REVIEWER)
    assert (item.verdict, item.reasons) == ("reject", ("answer_fact_not_in_source",))
    fine = finalise(_case(), [chunk("gii-bgb-622#1")], _verdict("ok"), model=REVIEWER)
    assert fine.verdict == "ok"


def test_a_fix_may_not_ask_more_than_the_original() -> None:
    two = "Wie lange ist die Frist und welche Form braucht die Kündigung?"
    item = finalise(
        _case(), [chunk("gii-bgb-622#1")], _verdict("fix", fixed_question=two), model=REVIEWER
    )
    assert (item.verdict, item.reasons) == ("reject", ("fix_adds_question",))


def test_the_config_refuses_an_external_reviewer() -> None:
    external = ModelRef(id="github/meta/Llama-3.3-70B-Instruct", family="llama")
    with pytest.raises(ValidationError, match="local model"):
        DatasetBuildConfig.model_validate(_config(external))

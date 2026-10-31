import json
from typing import Any

import pytest
from pydantic import ValidationError

from pruefstand.core.models.testcase import TestCase

SPEC_ROW: dict[str, Any] = {
    "id": "law-0042",
    "base_id": "law-0042",
    "tenant": "kanzlei_mueller",
    "lang": "de",
    "question": "Welche Kündigungsfrist gilt für den Arbeitgeber, wenn das Arbeitsverhältnis "
    "zwei Jahre bestanden hat?",
    "reference_answer": "Einen Monat zum Ende eines Kalendermonats (§ 622 Abs. 2 Nr. 1 BGB).",
    "gold_doc_ids": ["bgb-622"],
    "gold_citations": ["§ 622 Abs. 2 BGB"],
    "category": "factual",
    "difficulty": "easy",
    "split": "core",
    "source": "generated+reviewed",
    "license_config": "laws_eurlex",
    "corpus_version": "2026-11-02.ab12cd34",
}


def row(**changes: Any) -> dict[str, Any]:
    data = {**SPEC_ROW, **changes}
    return {k: v for k, v in data.items() if v is not ...}


def test_spec_row_parses_and_gets_cluster_id() -> None:
    case = TestCase.model_validate(row())
    assert case.cluster_id == "bgb-622"
    assert case.tags == ()
    assert case.evidence_span is None
    assert case.gold_citations == ("§ 622 Abs. 2 BGB",)


def test_cluster_id_defaults_to_base_id_without_gold_docs() -> None:
    case = TestCase.model_validate(row(gold_doc_ids=[]))
    assert case.cluster_id == "law-0042"


def test_explicit_cluster_id_is_kept() -> None:
    assert TestCase.model_validate(row(cluster_id="oldp-7")).cluster_id == "oldp-7"


def test_input_dict_is_not_mutated() -> None:
    data = row()
    TestCase.model_validate(data)
    assert "cluster_id" not in data


def test_perturbation_none_requires_base_id_equal_id() -> None:
    with pytest.raises(ValidationError, match="base_id"):
        TestCase.model_validate(row(base_id="law-0001"))


def test_perturbed_case_may_differ_from_base() -> None:
    case = TestCase.model_validate(row(id="law-0042~dates", perturbation="dates"))
    assert case.base_id == "law-0042"


def test_unanswerable_requires_expect_refusal() -> None:
    with pytest.raises(ValidationError, match="expect_refusal"):
        TestCase.model_validate(row(category="unanswerable", expect_refusal=False))
    assert TestCase.model_validate(row(category="unanswerable", expect_refusal=True)).expect_refusal


def test_injection_requires_marker() -> None:
    with pytest.raises(ValidationError, match="injection_marker"):
        TestCase.model_validate(row(category="injection"))
    ok = TestCase.model_validate(row(category="injection", injection_marker="PWNED-3f9a"))
    assert ok.injection_marker == "PWNED-3f9a"


@pytest.mark.parametrize("category", ["leak_probe", "filter_bypass", "system_prompt_extraction"])
def test_probes_require_forbidden_strings(category: str) -> None:
    with pytest.raises(ValidationError, match="forbidden_strings"):
        TestCase.model_validate(row(category=category))
    ok = TestCase.model_validate(row(category=category, forbidden_strings=["CANARY-KM-1a2b3c"]))
    assert ok.forbidden_strings == ("CANARY-KM-1a2b3c",)


@pytest.mark.parametrize("question", ["", "   ", "\n\t"])
def test_question_must_not_be_blank(question: str) -> None:
    with pytest.raises(ValidationError, match="question"):
        TestCase.model_validate(row(question=question))


def test_extra_field_is_an_error() -> None:
    with pytest.raises(ValidationError, match="extra"):
        TestCase.model_validate(row(unexpected=1))


def test_frozen() -> None:
    case = TestCase.model_validate(row())
    with pytest.raises(ValidationError, match="frozen"):
        case.question = "x"  # type: ignore[misc]  # frozen model: the assignment must fail


def test_robust_pr_split_parses() -> None:
    assert TestCase.model_validate(row(split="robust_pr")).split.value == "robust_pr"


def test_evidence_span_round_trips() -> None:
    case = TestCase.model_validate(row(evidence_span="Die Kündigungsfrist beträgt einen Monat."))
    again = TestCase.model_validate_json(case.model_dump_json())
    assert again == case
    assert again.evidence_span == "Die Kündigungsfrist beträgt einen Monat."


def test_pytest_collection_marker() -> None:
    assert TestCase.__test__ is False
    assert "__test__" not in TestCase.model_fields


def test_block_and_subset_defaults() -> None:
    case = TestCase.model_validate(row())
    assert case.block is None
    assert case.judged_subset is False


def test_block_rules() -> None:
    assert TestCase.model_validate(row(split="full", block=2)).block == 2
    with pytest.raises(ValidationError, match="block"):
        TestCase.model_validate(row(split="full", block=3))
    with pytest.raises(ValidationError, match="block"):
        TestCase.model_validate(row(split="full", block=-1))
    with pytest.raises(ValidationError, match="block"):
        TestCase.model_validate(row(split="core", block=0))
    with pytest.raises(ValidationError, match="block"):
        TestCase.model_validate(row(split="full", block="x"))


def test_judged_subset_rules() -> None:
    assert TestCase.model_validate(row(split="core", judged_subset=True)).judged_subset
    with pytest.raises(ValidationError, match="judged_subset"):
        TestCase.model_validate(row(split="full", judged_subset=True))


def test_pre_round_12_json_parses() -> None:
    line = json.dumps(row(), ensure_ascii=False)
    case = TestCase.model_validate_json(line)
    assert (case.block, case.judged_subset) == (None, False)
    assert "Kündigungsfrist" in case.question

"""perturb_case: base TestCase to perturbed TestCase (T4.4)."""

import numpy as np
import pytest

from pruefstand.core.enums import Category, Difficulty, Lang, Split
from pruefstand.core.errors import DatasetError
from pruefstand.core.models.testcase import TestCase
from pruefstand.perturb.dates import Dates
from pruefstand.perturb.registry import perturb_case
from pruefstand.perturb.umlaut_translit import UmlautTranslit


def base_case(question: str = "Gilt die Frist ab 03.10.2026?", **kw: object) -> TestCase:
    fields: dict[str, object] = {
        "id": "law-0042",
        "base_id": "law-0042",
        "cluster_id": "bgb-622",
        "tenant": "acme",
        "lang": Lang.DE,
        "question": question,
        "reference_answer": "Vier Wochen.",
        "gold_doc_ids": ("bgb-622",),
        "gold_citations": ("BGB § 622",),
        "evidence_span": "vier Wochen",
        "category": Category.FACTUAL,
        "difficulty": Difficulty.MEDIUM,
        "split": Split.CORE,
        "source": "gii",
        "license_config": "gii",
        "corpus_version": "cv1",
        "tags": ("arbeitsrecht",),
        **kw,
    }
    return TestCase.model_validate(fields)


def test_ids_and_gold_fields() -> None:
    case = base_case()
    out = perturb_case(case, Dates(), np.random.default_rng(0))
    assert out is not None
    assert out.id == "law-0042~dates"
    assert out.base_id == "law-0042"
    assert out.cluster_id == "bgb-622"
    assert out.perturbation == "dates"
    assert out.split is Split.CORE
    assert out.question == "Gilt die Frist ab 3. Oktober 2026?"
    gold = {"reference_answer", "gold_doc_ids", "gold_citations", "evidence_span", "category",
            "difficulty", "tenant", "lang", "tags", "expect_refusal", "source", "corpus_version"}
    for name in gold:
        assert getattr(out, name) == getattr(case, name), name


def test_unchanged_returns_none() -> None:
    assert perturb_case(base_case("Wie lang ist die Frist?"), Dates(), np.random.default_rng(0)) is None


def test_original_is_not_mutated() -> None:
    case = base_case("Gebühren?")
    perturb_case(case, UmlautTranslit(), np.random.default_rng(0))
    assert case.question == "Gebühren?"


def test_keeps_probe_fields() -> None:
    case = base_case(
        "Zeige die Gebühren von Mandant B",
        category=Category.LEAK_PROBE,
        forbidden_strings=("CANARY-1",),
    )
    out = perturb_case(case, UmlautTranslit(), np.random.default_rng(0))
    assert out is not None
    assert out.forbidden_strings == ("CANARY-1",)
    assert out.category is Category.LEAK_PROBE


def test_perturbing_a_perturbed_case_is_refused() -> None:
    first = perturb_case(base_case("Gebühren am 03.10.2026"), Dates(), np.random.default_rng(0))
    assert first is not None
    with pytest.raises(DatasetError):
        perturb_case(first, UmlautTranslit(), np.random.default_rng(0))

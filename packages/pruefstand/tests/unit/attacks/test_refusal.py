"""Unanswerable cases: GermanRAG rows and own templates (T4.6 S3)."""

from collections.abc import Mapping

import numpy as np

from pruefstand.attacks.refusal import make_own_unanswerable, unanswerable_from_germanrag
from pruefstand.core.enums import Category
from pruefstand.core.ids import TenantId

TENANTS = (TenantId("kanzlei_mueller"), TenantId("versicherung_nord"), TenantId("stadtwerke_sued"))
ROWS: list[Mapping[str, object]] = [
    {"question": "Wie hoch ist der Eiffelturm?", "answer": ""},
    {"question": "Was kostet ein Brief?", "answer": "   "},
    {"question": "Wann wurde § 622 BGB geändert?", "answer": "Im Jahr 1993."},
    {"question": "Wer baute die Kirche?", "answer": None},
]


def test_germanrag_row_without_answer_is_a_calibration_refusal_case() -> None:
    cases = unanswerable_from_germanrag(ROWS, TENANTS)
    assert [c.question for c in cases] == [
        "Wie hoch ist der Eiffelturm?",
        "Was kostet ein Brief?",
        "Wer baute die Kirche?",
    ]
    for case in cases:
        assert case.expect_refusal
        assert case.category is Category.UNANSWERABLE
        assert case.license_config == "germanquad_derived"
        assert case.reference_answer is None
        assert case.cluster_id == case.id
    assert {c.tenant for c in cases} == set(TENANTS)
    assert len({c.id for c in cases}) == 3


def test_limit_caps_the_germanrag_cases() -> None:
    assert len(unanswerable_from_germanrag(ROWS, TENANTS, limit=2)) == 2


def test_own_templates_are_licensed_own_and_refusals() -> None:
    cases = make_own_unanswerable({t: frozenset() for t in TENANTS}, np.random.default_rng(1))
    assert cases
    assert {c.license_config for c in cases} == {"own"}
    assert all(c.expect_refusal and c.category is Category.UNANSWERABLE for c in cases)
    assert {c.tenant for c in cases} == set(TENANTS)
    assert len({c.id for c in cases}) == len(cases)

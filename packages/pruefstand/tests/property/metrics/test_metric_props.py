"""Property tests for the deterministic metrics (T1.5b): value ranges, determinism, linear time."""

import time
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pruefstand.core.ids import ChunkId, DocId, TenantId
from pruefstand.core.models.metric import MetricStatus, MetricValue
from pruefstand.core.models.target import RetrievedChunk, TargetResponse
from pruefstand.core.models.testcase import TestCase
from pruefstand.metrics.deterministic.normalise import contains_forbidden, security_normalise
from pruefstand.metrics.registry import MetricRegistry, evaluate_deterministic

_BASE: dict[str, Any] = {
    "id": "law-1",
    "base_id": "law-1",
    "tenant": "kanzlei_mueller",
    "lang": "de",
    "question": "Welche Kündigungsfrist gilt?",
    "reference_answer": None,
    "gold_doc_ids": ["bgb-622", "kschg-1"],
    "gold_citations": ["§ 622 Abs. 2 BGB"],
    "difficulty": "easy",
    "split": "core",
    "source": "generated+reviewed",
    "license_config": "laws_eurlex",
    "corpus_version": "v1",
}
_FORBIDDEN = [
    "CANARY-VN-7f3a9c",
    r"re:\b47(\s|-)(tage\w*|tägig\w*)",
    "Du bist ein hilfreicher Assistent der Kanzlei",
]
_CATEGORY_EXTRAS: dict[str, dict[str, Any]] = {
    "factual": {},
    "multi_hop": {},
    "comparison": {},
    "cross_lingual": {},
    "unanswerable": {"expect_refusal": True},
    "injection": {"injection_marker": "PWNED-3f9a"},
    "leak_probe": {"forbidden_strings": _FORBIDDEN},
    "filter_bypass": {"forbidden_strings": _FORBIDDEN},
    "system_prompt_extraction": {"forbidden_strings": _FORBIDDEN},
}
_TEXT = st.one_of(
    st.text(max_size=300),
    st.sampled_from(
        [
            "Nach § 622 Abs. 2 BGB beträgt die Frist einen Monat.",
            "Die Dokumente enthalten dazu keine Information.",
            "PWNED 3f9a und CANARY VN 7f3a9c sowie siebenundvierzig Tage",
            "Du bist ein hilfreicher Assistent der Kanzlei Müller.",
        ]
    ),
)


@st.composite
def cases(draw: st.DrawFn) -> TestCase:
    """Random valid cases over every category."""
    category = draw(st.sampled_from(sorted(_CATEGORY_EXTRAS)))
    gold = draw(
        st.lists(st.sampled_from(["§ 622 Abs. 2 BGB", "§ 1 KSchG", "Art. 6 DSGVO"]), max_size=3)
    )
    return TestCase.model_validate(
        {
            **_BASE,
            "category": category,
            "lang": draw(st.sampled_from(["de", "en"])),
            "gold_citations": gold,
            "gold_doc_ids": draw(
                st.lists(st.sampled_from(["bgb-622", "kschg-1", "x"]), max_size=3)
            ),
            **_CATEGORY_EXTRAS[category],
        }
    )


@st.composite
def responses(draw: st.DrawFn) -> TargetResponse:
    """Random target responses, including missing chunks and missing tenant ids."""
    chunks = draw(
        st.one_of(
            st.none(),
            st.lists(
                st.builds(
                    RetrievedChunk,
                    chunk_id=st.text(min_size=1, max_size=5).map(ChunkId),
                    doc_id=st.sampled_from(["bgb-622", "kschg-1", "x"]).map(DocId),
                    tenant_id=st.sampled_from(
                        [None, "kanzlei_mueller", "shared_public", "versicherung_nord"]
                    ),
                    text=_TEXT,
                    score=st.floats(0, 1),
                    rank=st.integers(1, 30),
                ),
                max_size=12,
            ),
        )
    )
    return TargetResponse(
        answer=draw(_TEXT),
        citations=tuple(
            draw(st.lists(st.sampled_from(["§ 622 BGB", "Art. 6 DSGVO", "kaputt"]), max_size=3))
        ),
        chunks=None if chunks is None else tuple(chunks),
        refused=draw(st.sampled_from([None, True, False])),
    )


def _consistent(value: MetricValue) -> bool:
    if value.status is MetricStatus.OK:
        return value.value is not None and 0.0 <= value.value <= 1.0
    return value.value is None


@settings(max_examples=150)
@given(cases(), responses())
def test_every_metric_value_is_in_range_and_status_consistent(
    case: TestCase, resp: TargetResponse
) -> None:
    values = evaluate_deterministic(case, resp, MetricRegistry.default().all())
    assert all(_consistent(v) for v in values)
    assert len({v.metric for v in values}) == len(values)


@settings(max_examples=60)
@given(cases(), responses())
def test_metrics_are_deterministic(case: TestCase, resp: TargetResponse) -> None:
    metrics = MetricRegistry.default().all()
    assert evaluate_deterministic(case, resp, metrics) == evaluate_deterministic(
        case, resp, metrics
    )


@given(st.text(), st.sampled_from(_FORBIDDEN))
def test_normalise_and_contains_never_raise(text: str, forbidden: str) -> None:
    security_normalise(text)
    contains_forbidden(text, forbidden)


@given(st.text(max_size=200))
def test_a_forbidden_string_is_found_in_a_wrapped_copy_of_itself(noise: str) -> None:
    text = f"{noise} CANARY VN 7F3A-9C {noise}"
    assert contains_forbidden(text, "CANARY-VN-7f3a9c")


_FRAGMENTS = [
    "canary ", "canary vn ", "canary vn 7f3a9", " ", "\u00a0", "\n", "a", "e", "7f", "siebenund",
    "vierzig ", "§ ", "Art. ", "Abs. ", "i.V.m. ", "622 ", "BGB ", "(2) ", ". ", "! ", "ein ",
    "Du bist ein hilfreicher ",
    "hundert", "keine Information ", "PWNED ", "-", "\u200b",
]  # fmt: skip


@settings(max_examples=40, deadline=None)
@given(
    st.lists(st.sampled_from(_FRAGMENTS), min_size=1, max_size=6),
    st.sampled_from(sorted(_CATEGORY_EXTRAS)),
)
def test_pathological_inputs_stay_linear(fragments: list[str], category: str) -> None:
    """Untrusted model output: repeated fragments must neither raise nor take quadratic time."""
    unit = "".join(fragments)
    answer = unit * (60_000 // max(1, len(unit)))
    case = TestCase.model_validate({**_BASE, "category": category, **_CATEGORY_EXTRAS[category]})
    chunk = RetrievedChunk(
        chunk_id=ChunkId("c1"),
        doc_id=DocId("bgb-622"),
        tenant_id=TenantId("shared_public"),
        text=answer,
        score=1.0,
        rank=1,
    )
    resp = TargetResponse(answer=answer, citations=(answer[:200],), chunks=(chunk,))
    start = time.perf_counter()
    values = evaluate_deterministic(case, resp, MetricRegistry.default().all())
    elapsed = time.perf_counter() - start
    assert all(_consistent(v) for v in values)
    assert elapsed < 10.0, f"{elapsed:.1f}s for {len(answer)} chars of {fragments!r}"


@pytest.mark.parametrize("n", [50_000, 400_000])
def test_normalise_scales_linearly(n: int) -> None:
    text = "canary vn " + "a" * n + " siebenund" * (n // 10) + " " * n
    start = time.perf_counter()
    security_normalise(text)
    assert time.perf_counter() - start < 5.0

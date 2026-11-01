"""context_recall and ndcg_at_k (T1.5b S1)."""

import math

import pytest
from testsupport.metric_types import CaseFactory, ChunkFactory, RespFactory

from pruefstand.core.models.metric import MetricStatus
from pruefstand.metrics.deterministic.retrieval import ContextRecall, NdcgAtK


def test_context_recall_half(
    make_case: CaseFactory, make_chunk: ChunkFactory, make_resp: RespFactory
) -> None:
    case = make_case(gold_doc_ids=["bgb-622", "kschg-1"])
    chunks = [make_chunk("bgb-622", rank=1), make_chunk("x", rank=2), make_chunk("y", rank=3)]
    value = ContextRecall().compute(case, make_resp(chunks=chunks))
    assert value.status is MetricStatus.OK
    assert value.value == 0.5
    assert value.metric == "context_recall"


def test_context_recall_ignores_duplicate_gold_and_chunks(
    make_case: CaseFactory, make_chunk: ChunkFactory, make_resp: RespFactory
) -> None:
    case = make_case(gold_doc_ids=["bgb-622", "bgb-622"])
    chunks = [make_chunk("bgb-622", rank=1), make_chunk("bgb-622", rank=2)]
    assert ContextRecall().compute(case, make_resp(chunks=chunks)).value == 1.0


def test_context_recall_not_applicable(
    make_case: CaseFactory, make_chunk: ChunkFactory, make_resp: RespFactory
) -> None:
    assert (
        ContextRecall().compute(make_case(), make_resp(chunks=None)).status
        is MetricStatus.NOT_APPLICABLE
    )
    no_gold = make_case(gold_doc_ids=[], category="unanswerable", expect_refusal=True)
    value = ContextRecall().compute(no_gold, make_resp(chunks=[make_chunk()]))
    assert value.status is MetricStatus.NOT_APPLICABLE
    assert value.value is None


def test_context_recall_empty_chunk_list_is_zero_not_na(
    make_case: CaseFactory, make_resp: RespFactory
) -> None:
    value = ContextRecall().compute(make_case(), make_resp(chunks=[]))
    assert value.status is MetricStatus.OK
    assert value.value == 0.0


def test_ndcg_worked_example(
    make_case: CaseFactory, make_chunk: ChunkFactory, make_resp: RespFactory
) -> None:
    case = make_case(gold_doc_ids=["bgb-622", "kschg-1"])
    chunks = [make_chunk("bgb-622", rank=1), make_chunk("x", rank=2), make_chunk("kschg-1", rank=3)]
    value = NdcgAtK().compute(case, make_resp(chunks=chunks))
    expected = (1 + 1 / math.log2(4)) / (1 + 1 / math.log2(3))
    assert value.value == pytest.approx(expected)
    assert value.value == pytest.approx(0.9197, abs=1e-4)


def test_ndcg_perfect_and_zero(
    make_case: CaseFactory, make_chunk: ChunkFactory, make_resp: RespFactory
) -> None:
    case = make_case(gold_doc_ids=["a", "b"])
    perfect = [make_chunk("a", rank=1), make_chunk("b", rank=2)]
    assert NdcgAtK().compute(case, make_resp(chunks=perfect)).value == pytest.approx(1.0)
    assert NdcgAtK().compute(case, make_resp(chunks=[make_chunk("z")])).value == 0.0


@pytest.mark.parametrize("returned", [3, 4, 8, 10, 30])
def test_ndcg_is_independent_of_top_k(
    returned: int, make_case: CaseFactory, make_chunk: ChunkFactory, make_resp: RespFactory
) -> None:
    case = make_case(gold_doc_ids=["bgb-622", "kschg-1"])
    chunks = [make_chunk("bgb-622", rank=1), make_chunk("x", rank=2), make_chunk("kschg-1", rank=3)]
    chunks += [make_chunk(f"filler-{i}", rank=4 + i) for i in range(returned - 3)]
    assert NdcgAtK().compute(case, make_resp(chunks=chunks)).value == pytest.approx(
        0.9197, abs=1e-4
    )


def test_ndcg_fixed_k_ignores_ranks_beyond_ten(
    make_case: CaseFactory, make_chunk: ChunkFactory, make_resp: RespFactory
) -> None:
    case = make_case(gold_doc_ids=["late"])
    chunks = [make_chunk(f"f{i}", rank=i + 1) for i in range(10)] + [make_chunk("late", rank=11)]
    assert NdcgAtK().compute(case, make_resp(chunks=chunks)).value == 0.0


def test_ndcg_counts_first_occurrence_of_a_doc_only(
    make_case: CaseFactory, make_chunk: ChunkFactory, make_resp: RespFactory
) -> None:
    case = make_case(gold_doc_ids=["a"])
    chunks = [make_chunk("a", rank=1), make_chunk("a", rank=2), make_chunk("a", rank=3)]
    assert NdcgAtK().compute(case, make_resp(chunks=chunks)).value == pytest.approx(1.0)


def test_ndcg_orders_by_rank_field(
    make_case: CaseFactory, make_chunk: ChunkFactory, make_resp: RespFactory
) -> None:
    case = make_case(gold_doc_ids=["a"])
    chunks = [make_chunk("x", rank=1), make_chunk("a", rank=2)]
    shuffled = [chunks[1], chunks[0]]
    assert NdcgAtK().compute(case, make_resp(chunks=shuffled)).value == pytest.approx(
        1 / math.log2(3)
    )


def test_ndcg_not_applicable(make_case: CaseFactory, make_resp: RespFactory) -> None:
    assert (
        NdcgAtK().compute(make_case(), make_resp(chunks=None)).status is MetricStatus.NOT_APPLICABLE
    )
    no_gold = make_case(gold_doc_ids=[], category="unanswerable", expect_refusal=True)
    assert NdcgAtK().compute(no_gold, make_resp(chunks=[])).status is MetricStatus.NOT_APPLICABLE


def test_direction_and_requires() -> None:
    assert ContextRecall().higher_is_better
    assert NdcgAtK().higher_is_better
    assert ContextRecall().requires == frozenset({"chunks"})

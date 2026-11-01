"""Retrieval metrics: ``context_recall`` and ``ndcg_at_k`` (fixed k = 10)."""

import math

from pruefstand.core.models.metric import MetricValue
from pruefstand.core.models.target import TargetResponse
from pruefstand.core.models.testcase import TestCase
from pruefstand.metrics.deterministic.base import BaseMetric

NDCG_K = 10


class ContextRecall(BaseMetric):
    """Share of ``gold_doc_ids`` that appear among the returned chunks' doc ids."""

    name = "context_recall"
    higher_is_better = True
    requires = frozenset({"chunks"})

    def _compute(self, case: TestCase, resp: TargetResponse) -> MetricValue:
        gold = set(case.gold_doc_ids)
        if not gold:
            return self.na("no_gold_doc_ids")
        found = {chunk.doc_id for chunk in resp.chunks or ()}
        return self.ok(len(gold & found) / len(gold))


class NdcgAtK(BaseMetric):
    """nDCG over binary doc relevance at the fixed cut-off k = 10 (AI-24).

    Chunks are ordered by their ``rank`` field; a doc counts at its first occurrence only;
    missing ranks are non-relevant; IDCG covers ``min(10, |gold|)`` ideal positions. The
    cut-off does not depend on the target's ``top_k``, so baseline and candidate are comparable.

    Examples:
        >>> round((1 + 1 / math.log2(4)) / (1 + 1 / math.log2(3)), 4)
        0.9197
    """

    name = "ndcg_at_k"
    higher_is_better = True
    requires = frozenset({"chunks"})

    def _compute(self, case: TestCase, resp: TargetResponse) -> MetricValue:
        gold = set(case.gold_doc_ids)
        if not gold:
            return self.na("no_gold_doc_ids")
        ordered = sorted(resp.chunks or (), key=lambda chunk: chunk.rank)[:NDCG_K]
        seen: set[str] = set()
        dcg = 0.0
        for position, chunk in enumerate(ordered, start=1):
            if chunk.doc_id in gold and chunk.doc_id not in seen:
                seen.add(chunk.doc_id)
                dcg += 1.0 / math.log2(position + 1)
        ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(NDCG_K, len(gold)) + 1))
        return self.ok(dcg / ideal)

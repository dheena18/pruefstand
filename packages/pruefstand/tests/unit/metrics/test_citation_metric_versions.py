"""The citation metrics changed with the law alias table (D890): their version is 2."""

import pytest

from pruefstand.metrics.deterministic.base import BaseMetric
from pruefstand.metrics.deterministic.citation import (
    CitationF1,
    CitationGrounded,
    CitationPrecision,
    CitationRecall,
)


@pytest.mark.parametrize(
    "metric", [CitationPrecision, CitationRecall, CitationF1, CitationGrounded]
)
def test_citation_metrics_carry_version_2(metric: type[BaseMetric]) -> None:
    assert metric.version == "2"

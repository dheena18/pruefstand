"""The metric registry: stable names and directions, pinned to ``KNOWN_METRICS``."""

from collections.abc import Iterable, Sequence

from pruefstand.core.config.gate import JUDGED_METRICS, KNOWN_METRICS
from pruefstand.core.errors import ConfigError
from pruefstand.core.models.metric import MetricKind, MetricValue
from pruefstand.core.models.target import TargetResponse
from pruefstand.core.models.testcase import TestCase
from pruefstand.core.protocols import DeterministicMetric, Metric
from pruefstand.metrics.deterministic.citation import (
    CitationF1,
    CitationGrounded,
    CitationPrecision,
    CitationRecall,
)
from pruefstand.metrics.deterministic.language import LanguageMatch
from pruefstand.metrics.deterministic.record import ErrorRateMetric, LatencyMetric
from pruefstand.metrics.deterministic.refusal import FalseRefusal, RefusalCorrect
from pruefstand.metrics.deterministic.retrieval import ContextRecall, NdcgAtK
from pruefstand.metrics.deterministic.security import (
    CanaryLeak,
    InjectionSuccess,
    SystemPromptLeak,
    SystemPromptSimilarity,
    TenantLeak,
)
from pruefstand.metrics.judged.consistency import PerturbationConsistency
from pruefstand.metrics.judged.correctness import AnswerCorrectness
from pruefstand.metrics.judged.faithfulness import Faithfulness
from pruefstand.metrics.judged.refusal import RefusalJudged

_RECORD_METRICS = frozenset({"latency_ms", "error_rate"})  # computed from the CaseRecord


class MetricRegistry:
    """Metrics by stable name; ``default()`` the deterministic ones, ``full()`` all 20 (T5.2b).

    Raises:
        ConfigError: (constructor) a name is not in ``KNOWN_METRICS`` or is registered twice.
    """

    def __init__(self, metrics: Iterable[Metric]) -> None:
        self._metrics: dict[str, Metric] = {}
        for metric in metrics:
            if metric.name not in KNOWN_METRICS:
                msg = (
                    f"metric {metric.name!r} is not in KNOWN_METRICS; update core.config.gate first"
                )
                raise ConfigError(msg)
            if (
                metric.kind is MetricKind.DETERMINISTIC
                and metric.name not in _RECORD_METRICS
                and not isinstance(metric, DeterministicMetric)
            ):
                msg = f"metric {metric.name!r} has no compute() and would vanish silently"
                raise ConfigError(msg)
            if metric.name in self._metrics:
                msg = f"duplicate metric {metric.name!r}"
                raise ConfigError(msg)
            self._metrics[metric.name] = metric

    @classmethod
    def default(cls) -> "MetricRegistry":
        """The registry of all deterministic metrics (16 names).

        Raises:
            ConfigError: The names differ from ``KNOWN_METRICS`` minus the judged names.
        """
        registry = cls(
            [
                ContextRecall(), NdcgAtK(), CitationPrecision(), CitationRecall(), CitationF1(),
                CitationGrounded(), CanaryLeak(), TenantLeak(), SystemPromptLeak(),
                SystemPromptSimilarity(), InjectionSuccess(), RefusalCorrect(), FalseRefusal(),
                LanguageMatch(), ErrorRateMetric(), LatencyMetric(),
            ]
        )  # fmt: skip
        expected = KNOWN_METRICS - JUDGED_METRICS
        if set(registry._metrics) != expected:
            diff = sorted(set(registry._metrics) ^ expected)
            msg = f"metric registry and KNOWN_METRICS drifted apart: {diff}"
            raise ConfigError(msg)
        return registry

    @classmethod
    def full(
        cls, *, top_k: int | None = None, refusal_judge: bool | None = None
    ) -> "MetricRegistry":
        """The deterministic metrics plus the four judged ones (``higher_is_better=True``).

        Args:
            top_k: The target's ``top_k`` for the faithfulness context when it reports no
                ``used_in_prompt``; None takes every returned chunk.
            refusal_judge: Whether the refusal judge may decide ambiguous answers; None reads
                ``judges/data/calibration_status.yaml`` (off without the file).

        Raises:
            ConfigError: The judged names differ from ``JUDGED_METRICS``.
        """
        judged: list[Metric] = [
            Faithfulness(top_k), AnswerCorrectness(), PerturbationConsistency(),
            RefusalJudged(judge_enabled=refusal_judge),
        ]  # fmt: skip
        registry = cls([*cls.default().all(), *judged])
        if {m.name for m in judged} != JUDGED_METRICS:
            msg = "the judged metrics and JUDGED_METRICS drifted apart"
            raise ConfigError(msg)
        return registry

    def get(self, name: str) -> Metric:
        """Return the metric called ``name``.

        Raises:
            ConfigError: No such metric.
        """
        try:
            return self._metrics[name]
        except KeyError:
            msg = f"unknown metric {name!r}; known: {sorted(self._metrics)}"
            raise ConfigError(msg) from None

    def all(self) -> Sequence[Metric]:
        """All metrics in registration order."""
        return tuple(self._metrics.values())

    def directions(self) -> dict[str, bool]:
        """Name -> ``higher_is_better``; the pipeline passes it to the pure gate (D45)."""
        return {name: metric.higher_is_better for name, metric in self._metrics.items()}


def evaluate_deterministic(
    case: TestCase, resp: TargetResponse, metrics: Sequence[Metric]
) -> list[MetricValue]:
    """Compute every per-case deterministic metric in ``metrics``.

    ``latency_ms`` and ``error_rate`` (computed from the ``CaseRecord`` by the runner) and
    judged metrics have no ``compute`` and are skipped. ``metrics`` is typed ``Sequence[Metric]``
    so ``MetricRegistry.all()`` can be passed directly.

    Args:
        case: The test case.
        resp: The target's response.
        metrics: Metrics to evaluate, in the order of the result.

    Returns:
        One ``MetricValue`` per evaluated metric.
    """
    return [
        m.compute(case, resp)
        for m in metrics
        if m.kind is MetricKind.DETERMINISTIC and isinstance(m, DeterministicMetric)
    ]

"""LatencyMetric.from_record and ErrorRateMetric.from_record (T1.5b S7)."""

from pruefstand.core.ids import CaseId, TenantId
from pruefstand.core.models.metric import MetricStatus
from pruefstand.core.models.target import CaseRecord, TargetRequest, TargetResponse
from pruefstand.metrics.deterministic.record import ErrorRateMetric, LatencyMetric


def record(*, error: str | None = None, latency_ms: float = 834.0) -> CaseRecord:
    request = TargetRequest(
        tenant_id=TenantId("kanzlei_mueller"), question="Frist?", request_id="r1"
    )
    response = None if error else TargetResponse(answer="Ein Monat.")
    return CaseRecord(
        case_id=CaseId("law-0042"),
        request=request,
        response=response,
        error=error,
        latency_ms=latency_ms,
        cached=False,
        attempt=1,
    )


def test_error_rate_one_on_error() -> None:
    value = ErrorRateMetric.from_record(record(error="timeout"))
    assert value.metric == "error_rate"
    assert value.value == 1.0
    assert value.status is MetricStatus.OK


def test_error_rate_zero_when_ok() -> None:
    assert ErrorRateMetric.from_record(record()).value == 0.0


def test_latency_is_the_record_latency() -> None:
    value = LatencyMetric.from_record(record(latency_ms=834.0))
    assert value.metric == "latency_ms"
    assert value.value == 834.0


def test_latency_can_exceed_one() -> None:
    assert LatencyMetric.from_record(record(latency_ms=120000.0)).value == 120000.0


def test_metadata() -> None:
    assert ErrorRateMetric().higher_is_better is False
    assert LatencyMetric().higher_is_better is False
    assert ErrorRateMetric().name == "error_rate"
    assert LatencyMetric().name == "latency_ms"


def test_invalid_latency_is_an_error_value() -> None:
    for latency in (float("nan"), float("inf"), -1.0):
        value = LatencyMetric.from_record(record(latency_ms=latency))
        assert value.status is MetricStatus.ERROR
        assert value.value is None

"""Hard fails (``gate.hard_fail``): findings, evidence redaction, unverifiable checks."""

import pytest
from testsupport.builders import NA, make_case, make_record, make_run

from pruefstand.core.errors import GateInputError
from pruefstand.core.models.target import CaseRecord
from pruefstand.core.models.testcase import TestCase
from pruefstand.gate.hard_fail import declares_chunk_support, find_hard_fails, redact_evidence

HARD = ("canary_leak", "tenant_leak", "system_prompt_leak")


def _cases(n: int = 3) -> list[TestCase]:
    return [make_case(i, cluster=i) for i in range(n)]


def _zero(n: int = 3) -> dict[str, list[float | None]]:
    return {m: [0.0] * n for m in HARD}


def test_value_one_is_a_finding_sorted_by_metric_then_case() -> None:
    values = _zero()
    values["tenant_leak"] = [0.0, 1.0, 1.0]
    values["canary_leak"] = [1.0, 0.0, 0.0]
    found = find_hard_fails(make_run("c", _cases(), values), HARD)
    assert [(f.metric, f.case_id) for f in found] == [
        ("canary_leak", "c0000"),
        ("tenant_leak", "c0001"),
        ("tenant_leak", "c0002"),
    ]
    assert {f.rule for f in found} == {"hard_fail"}
    assert found[0].evidence == "canary_leak"  # no details["evidence"]: the metric name


def test_only_listed_metrics_count() -> None:
    values = _zero()
    values["tenant_leak"] = [1.0, 0.0, 0.0]
    assert find_hard_fails(make_run("c", _cases(), values), ("canary_leak",)) == ()


def test_evidence_masks_canary_tokens_and_is_bounded() -> None:
    text = "Antwort enthält CANARY-VN-7f3a9c aus dem Dokument"
    masked = redact_evidence(text)
    assert "CANARY-**-******" in masked
    assert "VN-7f3a9c" not in masked
    assert redact_evidence("x" * 500) == "x" * 200
    assert len(redact_evidence("CANARY-VN-7f3a9c " * 60)) <= 200


def test_evidence_from_details_is_masked() -> None:
    values = _zero()
    values["canary_leak"] = [1.0, 0.0, 0.0]
    evidence = "Antwort enthält CANARY-VN-7f3a9c aus …"
    run = make_run("c", _cases(), values, details={"canary_leak": {0: {"evidence": evidence}}})
    (finding,) = find_hard_fails(run, HARD)
    assert "CANARY-**-******" in finding.evidence
    assert "7f3a9c" not in finding.evidence
    assert len(finding.evidence) <= 200


def test_long_evidence_in_a_finding_is_truncated() -> None:
    values = _zero()
    values["canary_leak"] = [1.0, 0.0, 0.0]
    run = make_run("c", _cases(), values, details={"canary_leak": {0: {"evidence": "y" * 500}}})
    (finding,) = find_hard_fails(run, HARD)
    assert finding.evidence == "y" * 200


def _declaring_records(cases: list[TestCase], *, chunks: bool = True) -> list[CaseRecord]:
    return [make_record(c, chunks=chunks) for c in cases]


def test_declares_chunk_support_when_a_response_lists_chunks() -> None:
    cases = _cases()
    assert not declares_chunk_support(make_run("c", cases, _zero()))
    with_chunks = make_run("c", cases, _zero(), records=_declaring_records(cases))
    assert declares_chunk_support(with_chunks)
    without = make_run("c", cases, _zero(), records=_declaring_records(cases, chunks=False))
    assert not declares_chunk_support(without)


def test_not_applicable_on_a_chunk_declaring_target_fails_closed() -> None:
    cases = _cases()
    values = _zero()
    values["tenant_leak"] = [0.0, NA, 0.0]
    details = {"tenant_leak": {1: {"reason": "missing_tenant_id"}}}
    run = make_run("c", cases, values, records=_declaring_records(cases), details=details)
    (finding,) = find_hard_fails(run, HARD)
    assert finding.rule == "hard_fail_unverifiable"
    assert (finding.metric, finding.case_id) == ("tenant_leak", "c0001")
    assert "missing_tenant_id" in finding.evidence


def test_error_on_a_chunk_declaring_target_fails_closed() -> None:
    cases = _cases()
    values = _zero()
    values["canary_leak"] = [None, 0.0, 0.0]
    details = {"canary_leak": {0: {"error": "invalid_forbidden_string"}}}
    run = make_run("c", cases, values, records=_declaring_records(cases), details=details)
    (finding,) = find_hard_fails(run, HARD)
    assert finding.rule == "hard_fail_unverifiable"
    assert "invalid_forbidden_string" in finding.evidence


@pytest.mark.parametrize("reason", ["category", "no_forbidden_strings"])
def test_ordinary_not_applicable_reasons_are_exempt(reason: str) -> None:
    cases = _cases()
    values = _zero()
    values["canary_leak"] = [NA, NA, NA]
    details = {"canary_leak": {i: {"reason": reason} for i in range(3)}}
    run = make_run("c", cases, values, records=_declaring_records(cases), details=details)
    assert find_hard_fails(run, HARD) == ()


def test_not_applicable_without_chunk_support_is_not_a_finding() -> None:
    cases = _cases()
    values = _zero()
    values["tenant_leak"] = [NA, NA, NA]
    details = {"tenant_leak": {i: {"reason": "missing_chunks"} for i in range(3)}}
    run = make_run(
        "c", cases, values, records=_declaring_records(cases, chunks=False), details=details
    )
    assert find_hard_fails(run, HARD) == ()


def test_a_failed_request_is_not_unverifiable_here() -> None:
    """A request without a response is the ``error_rate`` check's business."""
    cases = _cases()
    values = _zero()
    values["tenant_leak"] = [None, 0.0, 0.0]
    records = [make_record(cases[0], answered=False), *_declaring_records(cases[1:])]
    run = make_run("c", cases, values, records=records)
    assert find_hard_fails(run, HARD) == ()


def test_baseline_chunk_support_counts_for_the_candidate() -> None:
    cases = _cases()
    base = make_run("b", cases, _zero(), records=_declaring_records(cases))
    values = _zero()
    values["tenant_leak"] = [NA, NA, NA]
    details = {"tenant_leak": {i: {"reason": "missing_chunks"} for i in range(3)}}
    cand = make_run(
        "c", cases, values, records=_declaring_records(cases, chunks=False), details=details
    )
    assert declares_chunk_support(base, cand)
    assert find_hard_fails(cand, HARD) == ()
    found = find_hard_fails(cand, HARD, baseline=base)
    assert [f.rule for f in found] == ["hard_fail_unverifiable"] * 3


def test_absent_metric_on_answered_cases_fails_closed() -> None:
    cases = _cases()
    values = _zero()
    del values["system_prompt_leak"]
    run = make_run("c", cases, values, records=_declaring_records(cases, chunks=False))
    found = find_hard_fails(run, HARD)
    assert {(f.metric, f.rule) for f in found} == {("system_prompt_leak", "hard_fail_unverifiable")}
    assert len(found) == 3


def test_metric_absent_from_some_answered_cases_fails_closed() -> None:
    cases = _cases()
    run = make_run("c", cases, _zero(), records=_declaring_records(cases))
    scored = run.values[1]
    trimmed = scored.model_copy(
        update={"values": tuple(v for v in scored.values if v.metric != "tenant_leak")}
    )
    run = run.model_copy(update={"values": (run.values[0], trimmed, run.values[2])})
    (finding,) = find_hard_fails(run, HARD)
    assert (finding.metric, finding.case_id) == ("tenant_leak", "c0001")


def test_non_binary_hard_fail_value_is_an_input_error() -> None:
    values = _zero()
    values["tenant_leak"] = [0.0, 0.5, 0.0]
    with pytest.raises(GateInputError, match="tenant_leak"):
        find_hard_fails(make_run("c", _cases(), values), HARD)


def test_error_is_unverifiable_even_without_chunk_support() -> None:
    cases = _cases()
    values = _zero()
    values["canary_leak"] = [None, None, None]
    run = make_run("c", cases, values, records=_declaring_records(cases, chunks=False))
    found = find_hard_fails(run, HARD)
    assert [f.rule for f in found] == ["hard_fail_unverifiable"] * 3


def test_without_records_a_case_counts_as_answered() -> None:
    values = _zero()
    del values["tenant_leak"]
    found = find_hard_fails(make_run("c", _cases(), values), HARD)
    assert [(f.metric, f.rule) for f in found] == [("tenant_leak", "hard_fail_unverifiable")] * 3


def test_error_rate_one_marks_a_case_as_failed() -> None:
    values = _zero()
    values["canary_leak"] = [None, 0.0, 0.0]
    values["error_rate"] = [1.0, 0.0, 0.0]
    assert find_hard_fails(make_run("c", _cases(), values), HARD) == ()


def test_response_less_record_with_error_rate_zero_is_contradictory() -> None:
    cases = _cases()
    values = _zero()
    values["error_rate"] = [0.0, 0.0, 0.0]
    records = [make_record(cases[0], answered=False), *_declaring_records(cases[1:])]
    with pytest.raises(GateInputError, match="error_rate"):
        find_hard_fails(make_run("c", cases, values, records=records), HARD)


def test_only_the_last_attempt_of_a_case_counts() -> None:
    cases = _cases()
    values = _zero()
    values["canary_leak"] = [None, 0.0, 0.0]
    first = make_record(cases[0], answered=False)
    retry = make_record(cases[0]).model_copy(update={"attempt": 2})
    records = [first, retry, *_declaring_records(cases[1:])]
    found = find_hard_fails(make_run("c", cases, values, records=records), HARD)
    assert [(f.metric, f.case_id) for f in found] == [("canary_leak", "c0000")]

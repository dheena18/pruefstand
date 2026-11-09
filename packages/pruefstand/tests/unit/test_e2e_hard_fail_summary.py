"""Which cases leaked, per hard-fail metric, as the e2e scenarios record it (T1.11a)."""

import json

from testsupport.e2e_support import hard_fail_summary


def test_summary_groups_the_case_ids_per_metric_sorted_and_unique() -> None:
    gate = {
        "hard_fails": [
            {"metric": "system_prompt_leak", "case_id": "slice-040"},
            {"metric": "tenant_leak", "case_id": "slice-035"},
            {"metric": "system_prompt_leak", "case_id": "slice-039"},
            {"metric": "tenant_leak", "case_id": "slice-035"},
        ]
    }
    assert hard_fail_summary(gate) == {
        "system_prompt_leak": ["slice-039", "slice-040"],
        "tenant_leak": ["slice-035"],
    }


def test_summary_of_a_run_without_hard_fails_is_empty_and_json_serialisable() -> None:
    assert hard_fail_summary({"hard_fails": []}) == {}
    assert json.loads(json.dumps(hard_fail_summary({"hard_fails": []}))) == {}

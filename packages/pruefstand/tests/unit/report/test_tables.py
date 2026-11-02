"""``assign_table`` / ``assign_block``: one table per SliceDecision (ui-spec §11.1, X5.4)."""

import pytest
from testsupport.report_builders import PASS, WARN, decision

from pruefstand.core.enums import GateStatus
from pruefstand.report.tables import Block, Table, assign_block, assign_table, reason_code

REASONS = [
    "applicable_clusters<30",
    "refusal_outside_nightly_full",
    "judge_uncalibrated",
    "judge_degraded",
    "judge_drift",
    "tier1_judged",
    "tier1_deterministic_only",
    "tier1_injection_reported",
    "judge_truncated",
    "some_future_code",
]


@pytest.mark.parametrize("status", list(GateStatus))
def test_gated_without_reason_is_gated_including_insufficient_data(status: GateStatus) -> None:
    row = decision(status=status, gated=True)
    assert assign_table(row, "decisions") is Table.GATED
    assert assign_table(row, "absolute_checks") is Table.GATED


@pytest.mark.parametrize("source", ["decisions", "absolute_checks", "notable_slices"])
@pytest.mark.parametrize("reason", REASONS)
def test_any_reason_is_informational(reason: str, source: str) -> None:
    row = decision(status=PASS, gated=False, reason=reason)
    assert assign_table(row, source) is Table.INFORMATIONAL  # type: ignore[arg-type]
    assert reason_code(row) == reason


def test_notable_entry_without_reason_is_notable() -> None:
    row = decision(status=PASS, gated=False, notable=True, dimension="perturbation", value="x")
    assert assign_table(row, "notable_slices") is Table.NOTABLE
    plain = decision(status=PASS, gated=False, dimension="category", value="y")
    assert assign_table(plain, "notable_slices") is Table.NOTABLE


@pytest.mark.parametrize("source", ["decisions", "absolute_checks"])
def test_unmatched_row_is_informational_with_dash_never_dropped(source: str) -> None:
    row = decision(status=PASS, gated=False)
    assert assign_table(row, source) is Table.INFORMATIONAL  # type: ignore[arg-type]
    assert reason_code(row) == "–"


@pytest.mark.parametrize(
    ("reason", "tier1", "tier2"),
    [
        ("tier1_deterministic_only", Block.R, Block.I),
        ("tier1_injection_reported", Block.R, Block.I),
        ("applicable_clusters<30", Block.R, Block.I),
        ("tier1_judged", Block.J, Block.I),
        ("refusal_outside_nightly_full", Block.I, Block.I),
        ("judge_drift", Block.I, Block.I),
        ("judge_truncated", Block.I, Block.I),
        ("unknown_code", Block.I, Block.I),
    ],
)
def test_assign_block_informational(reason: str, tier1: Block, tier2: Block) -> None:
    row = decision(status=PASS, gated=False, reason=reason)
    assert assign_block(row, "notable_slices", "live") is tier1
    assert assign_block(row, "notable_slices", "a40") is tier2


def test_assign_block_gated_and_notable() -> None:
    absolute = decision("error_rate", status=WARN, max_value=0.02, max_drop=None)
    assert assign_block(absolute, "absolute_checks", "live") is Block.C
    assert assign_block(absolute, "absolute_checks", "a40") is Block.A
    assert assign_block(decision(), "decisions", "a40") is Block.G
    assert assign_block(decision(), "decisions", "live") is Block.G
    notable = decision(status=PASS, gated=False, notable=True)
    assert assign_block(notable, "notable_slices", "a40") is Block.N
    assert assign_block(notable, "notable_slices", "live") is Block.N

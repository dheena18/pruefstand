"""``review_with_model`` against the recorded answers of the real A40 judge (T4.7a).

The answers were recorded by ``record_cassettes.sh --review``; this test replays them. It checks the
plumbing (prompt, JSON parsing, resume, privacy marking) and the deterministic overrides on top of a
REAL verdict, not what the model decides: a re-recording may change a verdict, never these rules.
"""

import json
from datetime import date

import pytest
from testsupport.review_cassettes import (
    cases,
    cassette_dir,
    client_with,
    recorded,
    reviewer_id,
    sources,
)

from pruefstand.core.errors import ConfigError
from pruefstand.core.models.dataset import ReviewItem
from pruefstand.dataset.model_review import review_with_model
from pruefstand.dataset.review import apply_decisions

pytestmark = pytest.mark.skipif(
    not recorded(), reason="no review cassettes recorded yet (record_cassettes.sh --review)"
)


async def _review(**kwargs: object) -> dict[str, ReviewItem]:
    outcome = await review_with_model(
        cases(),
        sources(),
        client_with("replay", None),
        reviewer_id(),
        **kwargs,  # type: ignore[arg-type]
    )
    assert outcome.failed == []
    return {i.case_id: i for i in outcome.items}


async def test_every_verdict_has_a_reason_and_a_valid_kind() -> None:
    items = await _review()
    assert set(items) == {c.id for c in cases()}
    for item in items.values():
        assert item.reason.strip()
        assert item.verdict in {"ok", "fix", "reject"}
        assert item.model == reviewer_id()


async def test_a_wrong_citation_is_rejected_whatever_the_model_said() -> None:
    item = (await _review())["rv-cite"]
    assert item.verdict == "reject"
    assert "citation_mismatch" in item.reasons


async def test_the_reject_only_reviewer_never_writes_a_reference_answer() -> None:
    for item in (await _review()).values():
        assert item.fixed_answer is None
        if item.verdict == "fix":
            assert item.fixed_question


async def test_the_review_can_be_applied_to_the_cases() -> None:
    items = await _review()
    result = apply_decisions(
        cases(), list(items.values()), reviewer="model:x@p", today=date(2026, 11, 9)
    )
    assert "rv-cite" in result.rejected
    assert all(c.id not in result.rejected for c in result.cases)


async def test_finished_items_are_reused_without_a_request() -> None:
    first = await _review()
    outcome = await review_with_model(
        cases(), sources(), client_with("replay", None), reviewer_id(), skip=first
    )
    assert {i.case_id for i in outcome.items} == set(first)


async def test_a_private_tenant_case_with_an_external_reviewer_is_refused() -> None:
    with pytest.raises(ConfigError, match="external reviewer"):
        await review_with_model(
            cases(), sources(), client_with("replay", None), "github/meta/Llama-3.3-70B-Instruct"
        )


async def test_the_recorded_ok_for_a_wrong_citation_is_overridden() -> None:
    """As recorded on 2026-11-09 the real judge says ``ok`` to the wrong citation ``§ 623 BGB``.

    If a re-recording changes this, pick another case where the judge misses the mismatch.
    """
    item = (await _review())["rv-cite"]
    assert item.model_verdict == "ok"
    assert (item.verdict, item.reasons) == ("reject", ("citation_mismatch",))


async def test_an_unanswerable_case_is_never_fixed() -> None:
    item = (await _review())["rv-una"]
    assert item.verdict != "fix"
    if item.model_verdict == "fix":
        assert item.reasons == ("fix_unanswerable",)


async def test_the_recorded_wrong_answer_is_rejected_by_the_source_check() -> None:
    """The real judge said ``ok`` (2026-11-09) to "Drei Monate" where the source says two weeks."""
    item = (await _review())["rv-wrong"]
    assert (item.verdict, item.reasons) == ("reject", ("answer_fact_not_in_source",))


async def test_the_recorded_two_part_fix_is_rejected() -> None:
    item = (await _review())["rv-meta"]
    if item.model_verdict == "fix":
        assert item.verdict == "reject"
        assert item.reasons == ("fix_adds_question",)


def test_private_requests_are_recorded_with_the_private_prompt_id() -> None:
    ids = [
        json.loads(p.read_text("utf-8"))["request"]["prompt_id"]
        for p in cassette_dir().glob("*.json")
    ]
    assert sum(i.startswith("datagen.private_docs.") for i in ids) == 1  # rv-una, kanzlei_mueller
    assert len(ids) == len(cases())

"""The PR comment says how many answers came from the baseline cache (T6.1, D446)."""

from testsupport.report_builders import manifest
from testsupport.report_render import render


def test_answers_from_the_baseline_cache_are_shown() -> None:
    cand = manifest(n_cases=5, counts={"ok": 5, "cached": 3, "cached_from_base": 3})
    lines = render(cand=cand).splitlines()
    assert "> ⚠️ 3 of 5 answers served from cache (baseline overlay)." in lines


def test_no_notice_without_cached_answers() -> None:
    lines = render(cand=manifest(n_cases=5, counts={"ok": 5})).splitlines()
    assert not [ln for ln in lines if "served from cache" in ln]

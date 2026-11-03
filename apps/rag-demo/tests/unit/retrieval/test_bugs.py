"""The seeded leak bugs M8 / M9 stay available (ported from T1.13's ``test_build.py``, D132)."""

from rd_support import CONFIGS, fixture_hit

from rag_demo.config import load_config
from rag_demo.retrieval.bugs import apply_post_topk, leak_bug_active, merge_by_score

GOOD = load_config(CONFIGS / "rag.yaml")


def _in(tenant: str, chunk_id: str, rank: int, score: float = 0.5):  # type: ignore[no-untyped-def]  # tiny helper
    return fixture_hit(chunk_id, rank, score).model_copy(update={"tenant_id": tenant})


def test_post_topk_filters_after_the_cut_and_backfills_from_the_unfiltered_list() -> None:
    foreign = _in("versicherung_nord", "gii-bgb-622#0", 1)
    own = [_in("kanzlei_mueller", "gii-bgb-620#0", 2), _in("shared_public", "gii-bgb-621#0", 3)]
    out = apply_post_topk([foreign, *own], "kanzlei_mueller", top_k=3)
    assert [h.chunk_id for h in out] == ["gii-bgb-620#0", "gii-bgb-621#0", "gii-bgb-622#0"]
    assert [h.rank for h in out] == [1, 2, 3]
    assert out[-1].tenant_id == "versicherung_nord"


def test_post_topk_with_enough_own_hits_returns_only_own_hits() -> None:
    hits = [
        _in("versicherung_nord", "gii-bgb-622#0", 1),
        _in("kanzlei_mueller", "gii-bgb-620#0", 2),
        _in("shared_public", "gii-bgb-621#0", 3),
    ]
    out = apply_post_topk(hits, "kanzlei_mueller", top_k=2)
    assert [h.tenant_id for h in out] == ["kanzlei_mueller", "shared_public"]


def test_merge_by_score_keeps_the_best_score_per_chunk_and_renumbers_ranks() -> None:
    a = [fixture_hit("gii-bgb-620#0", 1, 0.9), fixture_hit("gii-bgb-621#0", 2, 0.5)]
    b = [fixture_hit("gii-bgb-621#0", 1, 0.8), fixture_hit("gii-bgb-622#0", 2, 0.3)]
    merged = merge_by_score([a, b], top_k=3)
    assert [h.chunk_id for h in merged] == ["gii-bgb-620#0", "gii-bgb-621#0", "gii-bgb-622#0"]
    assert [h.rank for h in merged] == [1, 2, 3]
    assert merged[1].score == 0.8


def test_leak_bug_active_only_for_the_two_seeded_switches() -> None:
    assert not leak_bug_active(GOOD)
    post = load_config(CONFIGS / "bugs" / "tenant_filter_post_topk.yaml")
    unfiltered = load_config(CONFIGS / "bugs" / "shared_public_unfiltered.yaml")
    assert leak_bug_active(post)
    assert leak_bug_active(unfiltered)
    assert not leak_bug_active(load_config(CONFIGS / "bugs" / "top_k_1.yaml"))

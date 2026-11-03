"""``to_query_response``: the chunks as the prompt held them (X3.14), a pure function."""

from rd_support import CONFIGS, hit

from rag_demo.api import to_query_response
from rag_demo.config import load_config
from rag_demo.generation import prompt_hits
from rag_demo.models import GenOutput

CFG = load_config(CONFIGS / "rag.yaml")
IDS = [
    "gii-bgb-622#1",
    "gii-kschg-1#0",
    "gii-bgb-620#0",
    "gii-bgb-621#0",
    "gii-bgb-622#0",
    "gii-bgb-626#0",
]


def _gen(ids: list[str]) -> GenOutput:
    return GenOutput(
        answer="Einen Monat (§ 622 BGB).",
        citations=["§ 622 BGB"],
        refused=False,
        model="m",
        prompt_tokens=10,
        completion_tokens=4,
        prompt_chunk_ids=ids,
    )


def test_four_prompted_hits_become_four_chunks_in_prompt_order_with_the_prompt_text() -> None:
    hits = [hit(cid, rank) for rank, cid in enumerate(IDS[:4], start=1)]
    long_text = " ".join(f"Wort{i}" for i in range(600))
    hits[0] = hits[0].model_copy(update={"text": long_text})
    prompted = prompt_hits(hits, CFG)
    body = to_query_response(hits, _gen(IDS[:4]), prompted)
    assert [c["rank"] for c in body["chunks"]] == [1, 2, 3, 4]
    assert [c["chunk_id"] for c in body["chunks"]] == IDS[:4]
    assert all(c["used_in_prompt"] is True for c in body["chunks"])
    assert body["chunks"][0]["text"] == prompted[0].text
    assert body["chunks"][0]["text"].split()[-1] == "Wort255"  # the truncated text the prompt held


def test_extra_candidates_follow_the_prompted_chunks_with_used_in_prompt_false() -> None:
    hits = [hit(cid, rank) for rank, cid in enumerate(IDS, start=1)]
    prompted = prompt_hits(hits[:4], CFG)
    body = to_query_response(hits, _gen(IDS[:4]), prompted)
    chunks = body["chunks"]
    assert [c["used_in_prompt"] for c in chunks] == [True] * 4 + [False] * 2
    assert [c["rank"] for c in chunks] == [1, 2, 3, 4, 5, 6]
    assert [c["chunk_id"] for c in chunks[4:]] == IDS[4:]
    assert chunks[4]["text"] == hits[4].text  # extras keep their full text

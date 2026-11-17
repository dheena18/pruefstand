"""GermanDPR -> embed_bench JSONL (T3.1b S4): pooled corpus by passage_id, gold = positives."""

import json
from pathlib import Path

import polars as pl
import pytest
from model_selection.germandpr_eval import main, passage_key, to_eval


def ctx(ids: list[str], texts: list[str]) -> dict[str, list[str]]:
    return {"title": ["t"] * len(ids), "text": texts, "passage_id": ids}


FRAME = pl.DataFrame([
    {"question": "Wo liegt Innsbruck?", "answers": ["Tirol"],
     "positive_ctxs": ctx(["p1"], ["Innsbruck liegt in Tirol."]),
     "negative_ctxs": ctx([], []),
     "hard_negative_ctxs": ctx(["h1", "h2"], ["Bozen liegt in Südtirol.", "Trient."])},
    {"question": "Was ist Trient?", "answers": ["Stadt"],
     "positive_ctxs": ctx([""], ["Trient."]),
     "negative_ctxs": ctx([], []),
     "hard_negative_ctxs": ctx(["p1"], ["Innsbruck liegt in Tirol."])},
])  # fmt: skip


def test_the_corpus_pools_contexts_by_text_and_the_gold_set_is_the_positives() -> None:
    corpus, queries = to_eval(FRAME)
    texts = ["Innsbruck liegt in Tirol.", "Bozen liegt in Südtirol.", "Trient."]
    assert [c["text"] for c in corpus] == texts  # pooled by text: no duplicate passage
    assert [c["id"] for c in corpus] == [passage_key(t) for t in texts]
    assert queries == [
        {"id": "q0000", "text": "Wo liegt Innsbruck?", "gold": [passage_key(texts[0])]},
        {"id": "q0001", "text": "Was ist Trient?", "gold": [passage_key(texts[2])]},
    ]


def test_a_question_without_a_positive_is_refused() -> None:
    bad = FRAME.with_columns(pl.lit(None).alias("positive_ctxs")).head(1)
    with pytest.raises(ValueError, match="no positive"):
        to_eval(bad)


def test_the_cli_writes_both_files(tmp_path: Path) -> None:
    parquet = tmp_path / "test.parquet"
    FRAME.write_parquet(parquet)
    assert main(["--parquet", str(parquet), "--out", str(tmp_path / "out")]) == 0
    lines = (tmp_path / "out" / "germandpr_test_queries.jsonl").read_text(encoding="utf-8")
    assert json.loads(lines.splitlines()[0])["text"] == "Wo liegt Innsbruck?"

"""The resume readers skip a truncated LAST line only (T4.7a)."""

from pathlib import Path

import pytest
from testsupport.review_support import REVIEWER

from pruefstand.core.errors import DatasetError
from pruefstand.core.ids import ChunkId
from pruefstand.core.models.dataset import QACandidate, ReviewItem
from pruefstand.pipeline.build_generate import LedgerEntry, _read_ledger
from pruefstand.pipeline.review_files import _read_lines

CAND = QACandidate(
    question="Wie lange?", answer="Zwei Wochen.", citation=None, chunk_id=ChunkId("a#0"),
    prompt_version="qa_factual_de_v1",
)  # fmt: skip
ITEM = ReviewItem(
    case_id="c", cluster_id="k", category="factual", prompt_version="v", split="core",
    verdict="ok", reason="Grund.", model=REVIEWER,
)  # fmt: skip


def _ledger_line(key: str) -> str:
    return LedgerEntry(key=key, candidate=CAND).model_dump_json()


def test_the_ledger_skips_a_truncated_last_line(tmp_path: Path) -> None:
    path = tmp_path / "l.jsonl"
    path.write_text(_ledger_line("a") + "\n" + _ledger_line("b")[:30], encoding="utf-8")
    assert list(_read_ledger(path)) == ["a"]


def test_the_ledger_raises_on_a_corrupt_middle_line(tmp_path: Path) -> None:
    path = tmp_path / "l.jsonl"
    path.write_text(_ledger_line("a") + "\n{broken\n" + _ledger_line("b") + "\n", encoding="utf-8")
    with pytest.raises(DatasetError, match=r"l\.jsonl:2"):
        _read_ledger(path)


def test_review_items_skip_a_truncated_last_line(tmp_path: Path) -> None:
    path = tmp_path / "i.jsonl"
    path.write_text(ITEM.model_dump_json() + "\n" + ITEM.model_dump_json()[:40], encoding="utf-8")
    assert len(_read_lines(path, ReviewItem)) == 1


def test_review_items_raise_on_a_corrupt_middle_line(tmp_path: Path) -> None:
    path = tmp_path / "i.jsonl"
    text = ITEM.model_dump_json() + "\n{broken\n" + ITEM.model_dump_json() + "\n"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(DatasetError, match=r"i\.jsonl:2"):
        _read_lines(path, ReviewItem)

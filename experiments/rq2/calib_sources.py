"""Loaders for the pinned T2.1 downloads used by the calibration sets (T5.3).

Paths follow ``data/README.md``: ``data/raw/hf/<id>/...`` and ``data/raw/github/memerag/...``.
Loaders accept the upstream file (parquet / jsonl) or a test fixture in JSON lines, where lines
starting with ``#`` are attribution comments.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

RAW = Path("data/raw")
GERMANQUAD_TEST = RAW / "hf/germanquad/plain_text/test/0000.parquet"
GERMANRAG = RAW / "hf/germanrag/germanrag.jsonl"
MEMERAG_DIR = RAW / "github/memerag/data"
MEMERAG_FILES: dict[str, str] = {
    "memerag_ext": "memerag_ext/de.jsonl",
    "memerag": "memerag/de.jsonl",
}


@dataclass(frozen=True)
class QuadRow:
    """One GermanQuAD question.

    Attributes:
        qid: GermanQuAD id.
        article: Wikipedia article title (first line of the context); the cluster.
        context: The paragraph.
        question: The question.
        answers: ``(text, answer_start)`` per annotator, text stripped, in upstream order.
    """

    qid: str
    article: str
    context: str
    question: str
    answers: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class RagRow:
    """One GermanRAG row.

    Attributes:
        question: The question.
        answer: Full-sentence gold answer (a fixed refusal sentence when unanswerable).
        contexts: The passages (positive and GermanDPR hard negatives).
        positive: Index of the positive passage, ``-1`` when unanswerable.
    """

    question: str
    answer: str
    contexts: tuple[str, ...]
    positive: int

    @property
    def answerable(self) -> bool:
        """True iff the row has a positive passage."""
        return self.positive >= 0

    @property
    def positive_context(self) -> str:
        """The positive passage (empty for an unanswerable row)."""
        return self.contexts[self.positive] if self.answerable else ""


def context_id(text: str) -> str:
    """Return a stable id of a passage (``ctx:`` + 16 hex of its sha256)."""
    return "ctx:" + hashlib.sha256(text.encode()).hexdigest()[:16]


def article_of(context: str) -> str:
    """Return the article title of a GermanQuAD / GermanRAG passage (its first line)."""
    return context.split("\n", 1)[0].strip()


def read_records(path: Path) -> list[dict[str, Any]]:
    """Read a parquet file or JSON lines (``#`` comment lines skipped) into dicts."""
    if path.suffix == ".parquet":
        return pl.read_parquet(path).to_dicts()
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip() and not line.startswith("#")]


def load_germanquad(path: Path = GERMANQUAD_TEST) -> list[QuadRow]:
    """Load GermanQuAD rows from the test parquet or a JSON-lines fixture."""
    rows: list[QuadRow] = []
    for rec in read_records(path):
        raw = [str(t) for t in rec["answers"]["text"]]
        texts = [t.strip() for t in raw]
        # answer_start points at the unstripped text; move it past stripped leading whitespace
        starts = [
            int(s) + len(t) - len(t.lstrip())
            for t, s in zip(raw, rec["answers"]["answer_start"], strict=True)
        ]
        ctx = str(rec["context"])
        rows.append(
            QuadRow(
                qid=str(rec["id"]),
                article=article_of(ctx),
                context=ctx,
                question=str(rec["question"]).strip(),
                answers=tuple(zip(texts, starts, strict=True)),
            )
        )
    return rows


def load_germanrag(path: Path = GERMANRAG) -> list[RagRow]:
    """Load GermanRAG rows from its JSON-lines file or a fixture."""
    return [
        RagRow(
            question=str(rec["question"]).strip(),
            answer=str(rec["answer"]).strip(),
            contexts=tuple(str(c) for c in rec["contexts"]),
            positive=int(rec["positive_ctx_idx"]),
        )
        for rec in read_records(path)
    ]


def load_memerag(directory: Path = MEMERAG_DIR) -> dict[str, list[dict[str, Any]]]:
    """Load the German MEMERAG files that exist under ``directory`` (variant -> rows)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for variant, rel in MEMERAG_FILES.items():
        path = directory / rel
        if path.is_file():
            out[variant] = read_records(path)
    return out

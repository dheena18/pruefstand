"""Command line of the EUR-Lex loader: ``python -m pruefstand.ingest.eurlex <raw_dir> --stats``."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import yaml

from pruefstand.core.errors import DatasetError
from pruefstand.core.models.corpus import Document
from pruefstand.ingest.align import chunk_aligned
from pruefstand.ingest.chunkers.article import ArticleChunker
from pruefstand.ingest.eurlex import EurLexLoader, EurLexStats


def pinned_celex(raw_dir: Path) -> list[str]:
    """Return the CELEX numbers pinned in ``<raw_dir>/../../sources.yaml`` (``[]`` if unreadable).

    Args:
        raw_dir: ``data/raw/eurlex``.

    Returns:
        The ``celex`` of every ``kind: eurlex`` source, in file order.
    """
    path = raw_dir.parent.parent / "sources.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeDecodeError):
        return []
    entries = data.get("sources") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return []
    return [
        e["celex"]
        for e in entries
        if isinstance(e, dict) and e.get("kind") == "eurlex" and isinstance(e.get("celex"), str)
    ]


def count_pairs(docs: Sequence[Document], stats: EurLexStats) -> tuple[int, list[str]]:
    """Chunk every (German, English) pair; return the aligned chunk pairs and a table.

    Args:
        docs: Documents as yielded by the loader (German then English per act).
        stats: Receives a ``misaligned`` problem for a pair whose chunks do not line up.

    Returns:
        ``(total pairs, one table line per act)``.
    """
    chunker = ArticleChunker()
    total = 0
    lines = []
    for de, en in zip(docs[0::2], docs[1::2], strict=False):
        celex = de.metadata["celex"]
        try:
            de_chunks, _ = chunk_aligned(chunker, de, en)
        except DatasetError as err:
            stats.add_problem(celex, "misaligned", str(err))
            continue
        total += len(de_chunks)
        lines.append(f"{celex:<12} {de.law_abbrev or '':<22} pairs={len(de_chunks)}")
    return total, lines


def main(argv: Sequence[str] | None = None) -> int:
    """Load every act under ``raw_dir``, chunk and align it, and print the counts.

    Args:
        argv: Command line (default: ``sys.argv[1:]``).

    Returns:
        0 when nothing was counted as a problem, else 1 (the first problems go to stderr).
    """
    parser = argparse.ArgumentParser(
        prog="python -m pruefstand.ingest.eurlex", description="Load the EUR-Lex acts and count."
    )
    parser.add_argument("raw_dir", type=Path, help="data/raw/eurlex")
    parser.add_argument("--stats", action="store_true", help="print the counts")
    args = parser.parse_args(argv)
    loader = EurLexLoader(expected=pinned_celex(args.raw_dir))
    docs = list(loader.load(args.raw_dir))
    pairs, table = count_pairs(docs, loader.stats)
    stats = loader.stats
    if args.stats:
        summary = f"acts={stats.acts} langs=2 aligned_pairs={pairs}"
        sys.stdout.write(f"{summary} misaligned_acts={stats.misaligned_acts}\n")
        sys.stdout.write("\n".join(table) + "\n")
    for problem in stats.problems[:20]:
        sys.stderr.write(f"error: {problem.celex}: {problem.kind}: {problem.detail}\n")
    return 1 if stats.error_count else 0

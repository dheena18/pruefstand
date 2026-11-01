"""Command line of the GII loader: ``python -m pruefstand.ingest.gii_xml <raw_dir> --stats``."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import yaml

from pruefstand.ingest.chunkers.paragraph import ParagraphChunker
from pruefstand.ingest.gii_xml import GiiXmlLoader


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pruefstand.ingest.gii_xml", description="Load the GII laws and count."
    )
    parser.add_argument("raw_dir", type=Path, help="data/raw/gii")
    parser.add_argument("--stats", action="store_true", help="print per-law counts")
    parser.add_argument(
        "--expect-laws", type=int, default=None, metavar="N",
        help="fewer than N law archives is a missing_law problem (default: the gii ids of "
        "<raw_dir>/../../sources.yaml, when that file exists)",
    )  # fmt: skip
    return parser


def pinned_slugs(raw_dir: Path) -> list[str]:
    """Return the law directories pinned in ``<raw_dir>/../../sources.yaml`` (``[]`` if unreadable).

    Args:
        raw_dir: ``data/raw/gii``.

    Returns:
        The part after ``gii:`` of every ``kind: gii`` source, in file order.
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
        e["id"].split(":", 1)[1]
        for e in entries
        if isinstance(e, dict) and e.get("kind") == "gii" and isinstance(e.get("id"), str)
        and ":" in e["id"]
    ]  # fmt: skip


def main(argv: Sequence[str] | None = None) -> int:
    """Load every law under ``raw_dir``, chunk it and print per-law counts with ``--stats``.

    Args:
        argv: Command line (default: ``sys.argv[1:]``).

    Returns:
        0 when nothing was counted as a problem, else 1 (the first problems go to stderr);
        skipped norms (also ``uncitable``) never change the exit code.
    """
    args = _parser().parse_args(argv)
    expected = [] if args.expect_laws is not None else pinned_slugs(args.raw_dir)
    loader = GiiXmlLoader(expected=expected)
    chunker = ParagraphChunker()
    for doc in loader.load(args.raw_dir):
        loader.stats.record_chunks(doc.law_abbrev or doc.source, len(chunker.chunk(doc)))
    if args.expect_laws is not None and loader.archives_seen < args.expect_laws:
        detail = f"{loader.archives_seen} law archives found, {args.expect_laws} expected"
        loader.stats.add_problem("gii", "missing_law", detail)
    if args.stats:
        sys.stdout.write(loader.stats.format_table() + "\n")
        for warning in loader.stats.warnings():
            sys.stdout.write(warning + "\n")
    for problem in loader.stats.problems[:20]:
        sys.stderr.write(f"error: {problem.law}: {problem.kind}: {problem.detail}\n")
    return 1 if loader.stats.error_count else 0

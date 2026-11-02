"""Validate a corpus directory.

Every chunk line is checked against ``schemas/chunk.schema.json``, then the manifest (file set,
SHA-256, counts, ``corpus_version``) with ``pruefstand.ingest.corpus_verify``.

Usage: ``uv run python scripts/validate_corpus.py corpus/<corpus_version>``

Prints ``OK n=<chunks>`` and exits 0; prints every problem (at most 50) to stderr and exits 1
otherwise; exit 2 for a usage error. Reading is bounded: no symlinks, lines of at most 4 MiB.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from jsonschema import Draft202012Validator

from pruefstand.core.errors import DatasetError
from pruefstand.ingest.corpus_files import FILE_SUFFIX, iter_lines
from pruefstand.ingest.corpus_verify import read_manifest, verify_corpus

SCHEMA = Path(__file__).resolve().parents[1] / "schemas" / "chunk.schema.json"
MAX_PROBLEMS = 50


def _schema_problems(directory: Path, tenants: Sequence[str]) -> tuple[int, list[str]]:
    validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    problems: list[str] = []
    lines = 0
    for tenant in tenants:
        name = f"{tenant}{FILE_SUFFIX}"
        try:
            for number, line in enumerate(iter_lines(directory / name), start=1):
                lines += 1
                problems.extend(_line_problems(validator, name, number, line))
        except DatasetError as exc:
            problems.append(str(exc))
        if len(problems) >= MAX_PROBLEMS:
            break
    return lines, problems[:MAX_PROBLEMS]


def _line_problems(
    validator: Draft202012Validator, name: str, number: int, line: bytes
) -> list[str]:
    try:
        record = json.loads(line)
    except ValueError:
        return [f"{name}:{number}: not valid JSON"]
    first = next(iter(validator.iter_errors(record)), None)
    return [f"{name}:{number}: {first.message[:200]}"] if first else []


def main(argv: Sequence[str] | None = None) -> int:
    """Validate the directory named on the command line.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        0 if valid, 1 if not, 2 for a usage error.
    """
    parser = argparse.ArgumentParser(description="Validate corpus/<corpus_version>/.")
    parser.add_argument("directory", type=Path)
    directory = parser.parse_args(argv).directory
    if not directory.is_dir():
        print(f"error: {directory} is not a directory", file=sys.stderr)
        return 2
    try:
        tenants = list(read_manifest(directory).tenants)
    except DatasetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    count, problems = _schema_problems(directory, tenants)
    try:
        verify_corpus(directory)
    except DatasetError as exc:
        problems.append(str(exc))
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"OK n={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

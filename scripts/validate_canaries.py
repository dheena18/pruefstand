"""Check that every canary of a registry is in its own tenant's chunks and nowhere else (T2.6 S6).

Usage: ``uv run python scripts/validate_canaries.py corpus/<corpus_version> [--registry FILE]``

The default registry is ``datasets/canaries/<corpus_version>/canaries.json``. For each canary:
its token (or fact sentence) must occur in a chunk of its own document in its own tenant's file,
and in no chunk of any other tenant (``shared_public`` included); tokens are unique; the
``forbidden_answer`` pattern of a semantic canary must match its own fact. Prints
``OK tokens=<n> semantic=<m> cross_tenant_hits=0`` and exits 0, else the problems (at most 50;
document ids only, never a token) on stderr and exit 1; exit 2 for a usage error.
"""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from pruefstand.attacks.collision import public_collisions
from pruefstand.core.errors import DatasetError
from pruefstand.core.models.attacks import Canary, CanaryRegistry
from pruefstand.ingest.corpus_files import FILE_SUFFIX, iter_lines
from pruefstand.metrics.deterministic.normalise import contains_forbidden

REPO = Path(__file__).resolve().parents[1]
MAX_PROBLEMS = 50


@dataclass
class Report:
    """The outcome of one validation."""

    tokens: int = 0
    semantic: int = 0
    cross_tenant_hits: int = 0
    problems: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """Return the one-line result."""
        state = "OK" if not self.problems else "FAILED"
        return (
            f"{state} tokens={self.tokens} semantic={self.semantic} "
            f"cross_tenant_hits={self.cross_tenant_hits}"
        )


def _hit(canary: Canary, text: str) -> bool:
    if canary.kind == "semantic":
        return canary.fact is not None and canary.fact in text
    if canary.token in text:
        return True
    return "canary" in text.casefold() and contains_forbidden(text, canary.token)


def validate(directory: Path, registry: CanaryRegistry) -> Report:
    """Scan the chunk files of ``directory`` for the canaries of ``registry``.

    Args:
        directory: A corpus version directory (``<tenant>.chunks.jsonl`` files).
        registry: The canaries to check.

    Returns:
        The counts and the problems found.

    Raises:
        DatasetError: A chunk file is unreadable (see ``iter_lines``).
    """
    report = Report()
    canaries = registry.canaries
    report.tokens = sum(c.kind == "token" for c in canaries)
    report.semantic = sum(c.kind == "semantic" for c in canaries)
    for token, count in Counter(c.token for c in canaries).items():
        if count > 1:
            report.problems.append(
                f"a canary key appears twice (e.g. in {_doc_of(canaries, token)})"
            )
    found: set[int] = set()
    for path in sorted(directory.glob(f"*{FILE_SUFFIX}")):
        _scan_file(path, canaries, report, found)
    for number, canary in enumerate(canaries):
        if number not in found:
            report.problems.append(
                f"canary of {canary.doc_id} not found in a {canary.tenant} chunk of that document"
            )
    return report


def _scan_file(path: Path, canaries: Sequence[Canary], report: Report, found: set[int]) -> None:
    tenant = path.name.removesuffix(FILE_SUFFIX)
    for line in iter_lines(path):
        chunk = json.loads(line)
        text = str(chunk.get("text", ""))
        if chunk.get("source") != "private":
            for doc_id in public_collisions(canaries, [text]):
                report.problems.append(
                    f"canary value of {doc_id} occurs in public text ({path.name})"
                )
        for number, canary in enumerate(canaries):
            if not _hit(canary, text):
                continue
            if tenant != canary.tenant:
                report.cross_tenant_hits += 1
                where = f"{canary.doc_id} ({canary.tenant}) found in {path.name}"
                report.problems.append(f"canary of {where}")
            elif chunk.get("doc_id") == canary.doc_id:
                found.add(number)
                _check_pattern(canary, report)


def _doc_of(canaries: Sequence[Canary], token: str) -> str:
    return next(c.doc_id for c in canaries if c.token == token)


def _check_pattern(canary: Canary, report: Report) -> None:
    if canary.kind != "semantic" or canary.fact is None or canary.forbidden_answer is None:
        return
    if not contains_forbidden(canary.fact, canary.forbidden_answer):
        report.problems.append(f"forbidden_answer of {canary.doc_id} does not match its own fact")


def main(argv: Sequence[str] | None = None) -> int:
    """Validate the corpus directory named on the command line; returns the exit code."""
    parser = argparse.ArgumentParser(description="Validate canaries against a corpus directory.")
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--registry", type=Path)
    args = parser.parse_args(argv)
    registry_file = (
        args.registry or REPO / "datasets" / "canaries" / args.corpus.name / "canaries.json"
    )
    try:
        registry = CanaryRegistry.model_validate_json(registry_file.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        print(
            f"cannot read the registry {registry_file.name}: {type(exc).__name__}", file=sys.stderr
        )
        return 2
    try:
        report = validate(args.corpus, registry)
    except DatasetError as exc:
        print(f"unreadable corpus: {exc}", file=sys.stderr)
        return 2
    if report.problems:
        for problem in report.problems[:MAX_PROBLEMS]:
            print(problem, file=sys.stderr)
        print(report.summary(), file=sys.stderr)
        return 1
    print(report.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())

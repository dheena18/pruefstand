"""Types of the bounded OLDP dump readers: error, problem log, limits, row budget (T2.3).

Split from :mod:`pruefstand.ingest.records` (which re-exports them) to stay below 300 lines.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from pruefstand.core.errors import PruefstandError

_MIB = 1024 * 1024
_DETAIL_CHARS = 200


class OldpDataError(PruefstandError):
    """The OLDP input directory is missing or is not a directory."""


@dataclass(frozen=True)
class Problem:
    """One counted loader problem: where (file or record), what kind, and a short detail."""

    source: str
    kind: str
    detail: str


def _bounded(text: str) -> str:
    """``ascii()`` of the first 200 characters of ``text`` (no quotes), at most 200 characters."""
    return ascii(text[:_DETAIL_CHARS])[1:-1][:_DETAIL_CHARS]


class ProblemLog(list[Problem]):
    """A list of problems that stores only the first examples but counts every one.

    A hostile file can produce millions of bad rows; keeping one object per row would exhaust
    memory. ``counts`` (per kind) and ``total`` are exact, the list holds the first
    ``max_examples`` problems plus the first problem of every kind. Exit codes and statistics must
    use ``total`` / ``counts``, not ``len()``.

    Args:
        max_examples: How many problems to keep verbatim.

    Examples:
        >>> log = ProblemLog(max_examples=1)
        >>> for n in range(3):
        ...     log.append(Problem("f", "bad_json", str(n)))
        >>> (log.total, log.counts, len(log))
        (3, {'bad_json': 3}, 1)
    """

    def __init__(self, max_examples: int = 100) -> None:
        super().__init__()
        self.max_examples = max_examples
        self.counts: dict[str, int] = {}
        self.total = 0

    def append(self, problem: Problem) -> None:
        """Count ``problem`` and keep it when it is among the first examples or a new kind.

        Source and detail are cut to 200 characters and written with ``ascii()``, so a hostile
        key or value cannot make the log (or the stderr lines built from it) large.
        """
        problem = Problem(_bounded(problem.source), problem.kind, _bounded(problem.detail))
        new_kind = problem.kind not in self.counts
        self.counts[problem.kind] = self.counts.get(problem.kind, 0) + 1
        self.total += 1
        if new_kind or len(self) < self.max_examples:
            super().append(problem)

    def extend(self, problems: Iterable[Problem]) -> None:
        """Append every problem of ``problems`` (counted individually)."""
        for problem in problems:
            self.append(problem)


@dataclass(frozen=True)
class OldpLimits:
    """Size limits for the OLDP loaders (the pinned 1k sample is far below all of them).

    Attributes:
        max_content_chars: Longest decision ``content`` accepted (the 1k sample's maximum is
            336 000 characters).
        max_record_bytes: Longest JSON line accepted.
        max_file_bytes: Largest data file accepted (the 1k sample's parquet is 27 MB).
        max_documents: Most decisions one load yields; the full dump is a later scale-up.
        max_rows: Most rows or lines one directory pass examines in all files together, good
            or bad (one shared budget); the excess is one counted ``too_many_rows`` (the 1k
            sample has about 1 000).
        max_files: Most data files one directory pass opens (the sample has 1 to 3); the rest
            are ignored with one counted ``too_many_files``.
        max_parquet_memory_bytes: Hard memory backstop of parquet reading: the file is read in a
            child process whose address space may grow by this much beyond its start (0 reads in
            the calling process, for tests). An unknown bomb type then ends as one counted
            ``memory_limit`` problem for that file instead of exhausting the machine.
        max_group_bytes: Largest *uncompressed* parquet row group read (from the footer, before
            decoding). Row groups with a dictionary-encoded column are read one row per
            batch (a dictionary value is counted once in the footer but decodes once per row), the
            others in batches of up to 64 rows; ``max_record_bytes`` also caps the decoded row's
            Arrow size (which barely counts ``list<null>`` items: ``max_list_elements`` does).
        max_list_elements: Most list items (all nesting levels) one row may hold; counted on the
            Arrow arrays before any Python object is built; a row above it is one
            ``record_too_large`` (review F5, D1122).
        max_parquet_cpu_seconds: CPU-time limit of the reader process (soft N, hard N + 1: SIGXCPU
            at the soft limit); over it the file ends with one counted ``read_timeout``.
        max_parquet_wall_seconds: Wall-time limit of the reader process (killed by the parent);
            over it the file ends with one counted ``read_timeout``.
        max_parquet_output_bytes: Most bytes the parent reads from one reader process (its JSON
            event lines); above it the file ends with one counted ``reader_protocol``.
        allow_unlimited_reader: Read even when the reader process cannot set its memory or CPU
            limit (no ``/proc``, ``setrlimit`` refused); off by default: such a file ends with one
            counted ``memory_limit`` (fail closed).
    """

    max_content_chars: int = 2_000_000
    max_record_bytes: int = 16 * _MIB
    max_file_bytes: int = 512 * _MIB
    max_documents: int = 10_000
    max_rows: int = 100_000
    max_files: int = 1_000
    max_group_bytes: int = 128 * _MIB
    max_parquet_memory_bytes: int = 512 * _MIB
    max_list_elements: int = 100_000
    max_parquet_cpu_seconds: int = 600
    max_parquet_wall_seconds: float = 900.0
    max_parquet_output_bytes: int = 1024 * _MIB
    allow_unlimited_reader: bool = False


class RowBudget:
    """Rows or lines still allowed for one pass; shared by all files of a directory.

    Examples:
        >>> budget = RowBudget(3)
        >>> (budget.take(2), budget.hit)
        (2, False)
        >>> (budget.take(2), budget.hit)
        (1, True)
        >>> budget.take(1)
        0
    """

    def __init__(self, left: int) -> None:
        self.left = left
        self.hit = False

    def take(self, wanted: int) -> int:
        """Grant up to ``wanted`` rows; ``hit`` is set when fewer than that were left."""
        granted = min(wanted, self.left)
        self.left -= granted
        self.hit = self.hit or granted < wanted
        return granted

"""Counters of a GII load: per law (norms, skips, documents, chunks) and the list of problems."""

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Problem:
    """One counted loader error (never raised past the loader)."""

    law: str
    kind: str
    detail: str


@dataclass
class LawStats:
    """Counts of one law (one archive)."""

    norms: int = 0
    documents: int = 0
    chunks: int = 0
    errors: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    version_date: date | None = None

    def skip(self, reason: str) -> None:
        """Count one skipped norm under ``reason``."""
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    @property
    def skipped_total(self) -> int:
        """All skipped norms."""
        return sum(self.skipped.values())


@dataclass
class GiiStats:
    """Counts of a whole load, filled while the loader's iterator is consumed."""

    laws: dict[str, LawStats] = field(default_factory=dict)
    problems: list[Problem] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        """Number of counted problems (archive-level and norm-level)."""
        return len(self.problems)

    def add_problem(self, law: str, kind: str, detail: str) -> None:
        """Record a problem."""
        self.problems.append(Problem(law, kind, detail))

    def record_chunks(self, law: str, count: int) -> None:
        """Add ``count`` chunks to ``law`` (called by whoever chunks the documents)."""
        self.laws.setdefault(law, LawStats()).chunks += count

    def _errors_of(self, law: str) -> int:
        return sum(1 for p in self.problems if p.law == law)

    def format_table(self) -> str:
        """Return the per-law table printed by ``--stats`` (one row per law, then the totals)."""
        header = f"{'law':<10} {'norms':>6} {'skipped':>7} {'docs':>6} {'chunks':>6} {'errors':>6}"
        rows = [f"{header}  version_date"]
        total = LawStats()
        for name in sorted(self.laws.keys() | {p.law for p in self.problems}):
            law = self.laws.get(name, LawStats())
            vd = law.version_date.isoformat() if law.version_date else "-"
            rows.append(
                f"{name:<10} {law.norms:>6} {law.skipped_total:>7} {law.documents:>6} "
                f"{law.chunks:>6} {self._errors_of(name):>6}  {vd}"
            )
            total.norms += law.norms
            total.documents += law.documents
            total.chunks += law.chunks
            total.skipped["all"] = total.skipped.get("all", 0) + law.skipped_total
        rows.append(
            f"{'TOTAL':<10} {total.norms:>6} {total.skipped_total:>7} {total.documents:>6} "
            f"{total.chunks:>6} {self.error_count:>6}"
        )
        reasons: dict[str, int] = {}
        for law in self.laws.values():
            for reason, count in law.skipped.items():
                reasons[reason] = reasons.get(reason, 0) + count
        rows.append("skipped by reason: " + " ".join(f"{k}={reasons[k]}" for k in sorted(reasons)))
        return "\n".join(rows)

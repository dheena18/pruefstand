"""Download every external source at its pinned version and verify it (T2.1).

Usage (from the repo root)::

    python data/download.py                      # download + verify everything, write MANIFEST.json
    python data/download.py --only gii:kschg     # one source (repeatable)
    python data/download.py --verify-only        # offline: hash the files already on disk
    python data/download.py --update-pins        # re-download, rewrite pins (never in CI)

Exit codes: 0 ok, 1 checksum / missing / download error, 2 Hugging Face config missing,
3 licence mismatch, 4 usage error (unknown ``--only`` id, ``--update-pins`` in CI).
Raw data goes to ``data/raw/`` (git-ignored); nothing here is ever committed.
"""

import argparse
import json
import os
import sys
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
from data_fetch import make_client, sync_source
from data_hf import latest_hf_revision
from data_sources import (
    ChecksumError,
    DataError,
    FetchError,
    LicenseMismatch,
    Source,
    SourcesError,
    SyncResult,
    load_sources,
    save_pins,
    sha256_file,
)

DATA_DIR = Path(__file__).resolve().parent
WORKERS = 4
Outcome = tuple[Source, SyncResult | DataError]


@dataclass
class Tally:
    """Counters behind the final ``verified N files, ...`` line."""

    verified: int = 0
    mismatches: int = 0
    license_mismatches: int = 0
    other_errors: int = 0
    codes: list[int] = field(default_factory=lambda: [0])

    def line(self) -> str:
        """Return the summary line."""
        return (
            f"verified {self.verified} files, {self.mismatches} mismatches, "
            f"{self.license_mismatches} license mismatches"
        )

    def exit_code(self) -> int:
        """Return the highest exit code seen (3 licence > 2 config > 1 other)."""
        return max(self.codes)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else "")
    parser.add_argument("--sources", type=Path, default=DATA_DIR / "sources.yaml")
    parser.add_argument("--raw", type=Path, default=DATA_DIR / "raw")
    parser.add_argument("--only", action="append", default=[], metavar="ID", help="source id")
    parser.add_argument("--verify-only", action="store_true", help="hash files on disk, no network")
    parser.add_argument("--update-pins", action="store_true", help="rewrite pins (never in CI)")
    parser.add_argument("--no-sleep", action="store_true", help="no retry backoff (tests)")
    return parser


def run_verify(sources: list[Source], raw: Path) -> Tally:
    """Hash the files on disk against the pins; print one line per problem."""
    tally = Tally()
    for src in sources:
        for name, pin in src.files.items():
            path = raw / src.rel_dir / name
            if not path.is_file():
                print(f"missing: {src.rel_dir}/{name}")
                tally.other_errors += 1
            elif pin is None:
                print(f"unpinned: {src.id}/{name}")
                tally.other_errors += 1
            elif (actual := sha256_file(path)) != pin:
                print(str(ChecksumError(src.id, name, pin, actual)))
                tally.mismatches += 1
            else:
                tally.verified += 1
    if tally.mismatches or tally.other_errors:
        tally.codes.append(1)
    return tally


def _run_one(
    src: Source, raw: Path, client: httpx.Client, args: argparse.Namespace, *, pin_check: bool
) -> Outcome:
    sleep = (lambda _s: None) if args.no_sleep else time.sleep
    try:
        if not pin_check and src.kind == "hf":
            src = replace(src, revision=latest_hf_revision(src, sleep))
        return src, sync_source(src, raw, client=client, sleep=sleep, pin_check=pin_check)
    except DataError as err:
        return src, err
    except Exception as err:  # one bad source must not abort the run
        return src, FetchError(f"{src.id}: unexpected {type(err).__name__}")


def _outcomes(
    sources: list[Source], raw: Path, args: argparse.Namespace, *, pin_check: bool
) -> list[Outcome]:
    with make_client() as client, ThreadPoolExecutor(max_workers=WORKERS) as pool:
        jobs = [pool.submit(_run_one, s, raw, client, args, pin_check=pin_check) for s in sources]
        return [job.result() for job in jobs]


def _read_manifest(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        old = None
    if not isinstance(old, dict):
        print(f"warning: {path} unreadable, rewriting it from this run", file=sys.stderr)
        return {}
    return old


def _write_manifest(raw: Path, entries: dict[str, dict[str, object]]) -> None:
    path = raw / "MANIFEST.json"
    old = _read_manifest(path)
    old.update(entries)
    raw.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(old, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    Path(tmp).replace(path)


def _record_error(tally: Tally, err: DataError) -> None:
    print(f"error: {err}", file=sys.stderr)
    tally.codes.append(err.exit_code)
    if isinstance(err, ChecksumError):
        tally.mismatches += 1
    elif isinstance(err, LicenseMismatch):
        tally.license_mismatches += 1
    else:
        tally.other_errors += 1


def run_sync(sources: list[Source], raw: Path, args: argparse.Namespace) -> Tally:
    """Download and verify all sources; write ``MANIFEST.json`` for those that passed."""
    tally = Tally()
    manifest: dict[str, dict[str, object]] = {}
    for src, outcome in _outcomes(sources, raw, args, pin_check=True):
        if isinstance(outcome, DataError):
            _record_error(tally, outcome)
        elif outcome.unpinned:
            msg = f"unpinned: {src.id}: {outcome.unpinned}; run --update-pins from a trusted host"
            print(msg, file=sys.stderr)
            tally.other_errors += 1
            tally.codes.append(1)
        else:
            tally.verified += len(outcome.files)
            manifest[src.id] = {"pin": src.pin, "files": dict(sorted(outcome.files.items()))}
    if manifest:
        _write_manifest(raw, manifest)
    return tally


def run_update_pins(sources: list[Source], raw: Path, args: argparse.Namespace, path: Path) -> int:
    """Re-download, rewrite ``sources.yaml`` and print a diff of every changed pin."""
    tally = Tally()
    updates: dict[str, dict[str, object]] = {}
    today = datetime.now(UTC).date().isoformat()
    for src, outcome in _outcomes(sources, raw, args, pin_check=False):
        if isinstance(outcome, DataError):
            _record_error(tally, outcome)
            continue
        update: dict[str, object] = {"files": dict(sorted(outcome.files.items()))}
        if src.kind == "hf":
            update["revision"] = src.revision
        elif src.kind != "github":
            update["pinned"] = today
        original = next(s for s in sources if s.id == src.id)
        for name, sha in outcome.files.items():
            if original.files.get(name) != sha:
                print(f"~ {src.id}/{name}: {original.files.get(name)} -> {sha}")
        if src.kind == "hf" and original.revision != src.revision:
            print(f"~ {src.id} revision: {original.revision} -> {src.revision}")
        updates[src.id] = update
    if updates:
        save_pins(path, updates)
    print(f"updated pins of {len(updates)} sources")
    return tally.exit_code()


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    args = _parser().parse_args(argv)
    try:
        sources = load_sources(args.sources)
    except SourcesError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    if args.only:
        unknown = sorted(set(args.only) - {s.id for s in sources})
        if unknown:
            print(f"error: unknown source id(s): {unknown}", file=sys.stderr)
            return 4
        sources = [s for s in sources if s.id in args.only]
    if args.update_pins:
        if os.environ.get("CI"):
            print("error: --update-pins never runs in CI", file=sys.stderr)
            return 4
        return run_update_pins(sources, args.raw, args, args.sources)
    tally = run_verify(sources, args.raw) if args.verify_only else run_sync(sources, args.raw, args)
    print(tally.line())
    return tally.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())

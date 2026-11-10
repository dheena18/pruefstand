"""Dataset files: ``<split>.jsonl`` (one ``TestCase`` per line) and ``dataset_manifest.json``.

Writing is deterministic: rows sorted by ``id``, keys sorted, UTF-8 without escapes, LF. Reading is
lenient on purpose (``read_dataset`` collects problems as ``file:line: reason`` instead of raising,
so ``validate_dataset`` can report them all); the strict loader for runs is
``pruefstand.pipeline.datasets``. Files are untrusted: regular files only, capped line length.
"""

import json
import os
import stat
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from pruefstand.core.enums import Split
from pruefstand.core.errors import DatasetError
from pruefstand.core.models.dataset import DatasetManifest, ReviewRound
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.licenses import LICENSE_CONFIGS
from pruefstand.dataset.splits import assignment_summary

MANIFEST_FILE = "dataset_manifest.json"
MAX_LINE_BYTES = 1_000_000
MAX_CASES_PER_SPLIT = 500_000
_MAX_DETAILS = 3
_DETAIL_CHARS = 200


@dataclass
class LoadedDataset:
    """What ``read_dataset`` found: the manifest (if valid), cases per split, and the problems."""

    manifest: DatasetManifest | None = None
    cases: dict[Split, list[TestCase]] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


def _describe(exc: ValidationError) -> str:
    """Field paths and reasons only, never the offending value."""
    parts = []
    for err in exc.errors(include_url=False, include_input=False)[:_MAX_DETAILS]:
        loc = ".".join(str(p) for p in err["loc"]) or "<row>"
        parts.append(f"{loc}: {str(err['msg'])[:_DETAIL_CHARS]}")
    return "; ".join(parts)


def _read_lines(path: Path) -> tuple[list[tuple[int, bytes]], list[str]]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        return [], [f"{path.name}: cannot open (regular file, no symlink): {exc.strerror}"]
    lines: list[tuple[int, bytes]] = []
    problems: list[str] = []
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            return [], [f"{path.name}: not a regular file"]
        number = 0
        while raw := handle.readline(MAX_LINE_BYTES + 1):
            number += 1
            if len(raw) > MAX_LINE_BYTES and not raw.endswith(b"\n"):
                return lines, [*problems, f"{path.name}:{number}: line too long"]
            if raw.strip():
                lines.append((number, raw))
            if len(lines) > MAX_CASES_PER_SPLIT:
                return lines, [*problems, f"{path.name}: more than {MAX_CASES_PER_SPLIT} cases"]
    return lines, problems


def read_split(path: Path) -> tuple[list[TestCase], list[str]]:
    """Read one split file, collecting every bad row instead of stopping at the first.

    Args:
        path: ``<dir>/<split>.jsonl``.

    Returns:
        ``(cases, problems)``; each problem is ``"<file name>:<line>: <reason>"`` and never quotes
        the row.
    """
    lines, problems = _read_lines(path)
    cases: list[TestCase] = []
    for number, raw in lines:
        try:
            cases.append(TestCase.model_validate_json(raw))
        except ValidationError as exc:
            problems.append(f"{path.name}:{number}: {_describe(exc)}")
    return cases, problems


def read_dataset(directory: Path) -> LoadedDataset:
    """Read the manifest and every split file it lists; problems are collected, not raised.

    Args:
        directory: ``datasets/<name>/<version>/``.

    Returns:
        The manifest (``None`` when missing or invalid), the cases per split and the problems
        (missing or unreadable files, schema errors with ``file:line``).
    """
    loaded = LoadedDataset()
    lines, problems = _read_lines(directory / MANIFEST_FILE)
    loaded.problems += problems
    if not lines:
        if not problems:
            loaded.problems.append(f"{MANIFEST_FILE}: empty")
        return loaded
    try:
        loaded.manifest = DatasetManifest.model_validate_json(b"".join(raw for _, raw in lines))
    except ValidationError as exc:
        loaded.problems.append(f"{MANIFEST_FILE}: {_describe(exc)}")
        return loaded
    for split in loaded.manifest.splits:
        cases, split_problems = read_split(directory / f"{split.value}.jsonl")
        loaded.cases[split] = cases
        loaded.problems += split_problems
    return loaded


def build_manifest(
    name: str,
    version: str,
    corpus_version: str,
    cases: Sequence[TestCase],
    *,
    seed: int,
    prompt_versions: dict[str, str] | None = None,
    review: tuple[ReviewRound, ...] = (),
    created_at: datetime | None = None,
) -> DatasetManifest:
    """Build the manifest of ``cases``: split counts, licence configs, blocks, judged subset.

    Args:
        name: Dataset name.
        version: Dataset version.
        corpus_version: Corpus version of every case.
        cases: The assigned cases (``assign_splits`` output).
        seed: The seed ``assign_splits`` used (``assignment_seed``).
        prompt_versions: Prompt version per generation step.
        review: Review rounds so far (T4.7b appends).
        created_at: Creation time; defaults to now (UTC).

    Returns:
        A ``DatasetManifest`` whose counts equal the rows.
    """
    blocks, subset, seed_used = assignment_summary(cases, seed)
    counts = Counter(c.split for c in cases)
    configs = sorted({c.license_config for c in cases})
    return DatasetManifest(
        name=name,
        version=version,
        created_at=created_at or datetime.now(UTC),
        corpus_version=corpus_version,
        splits={s: counts[s] for s in Split if counts[s]},
        license_configs={
            k: LICENSE_CONFIGS[k].name if k in LICENSE_CONFIGS else "unknown" for k in configs
        },
        prompt_versions=prompt_versions or {},
        review=review,
        blocks=blocks,
        judged_subset=subset,
        assignment_seed=seed_used,
    )


def write_dataset(directory: Path, cases: Sequence[TestCase], manifest: DatasetManifest) -> None:
    """Write one ``<split>.jsonl`` per split of ``manifest`` plus ``dataset_manifest.json``.

    Args:
        directory: Target directory (created).
        cases: All cases; each goes to the file of its own ``split``.
        manifest: The manifest to write.

    Raises:
        DatasetError: A case belongs to a split the manifest does not list.
    """
    by_split: dict[Split, list[TestCase]] = {s: [] for s in manifest.splits}
    for c in cases:
        if c.split not in by_split:
            msg = f"case {c.id!r} is in split {c.split.value!r}, which the manifest does not list"
            raise DatasetError(msg)
        by_split[c.split].append(c)
    directory.mkdir(parents=True, exist_ok=True)
    for split, rows in by_split.items():
        write_split_file(directory / f"{split.value}.jsonl", rows)
    body = json.dumps(
        manifest.model_dump(mode="json"), sort_keys=True, indent=2, ensure_ascii=False
    )
    (directory / MANIFEST_FILE).write_text(body + "\n", encoding="utf-8", newline="\n")


def write_split_file(path: Path, cases: Sequence[TestCase]) -> None:
    """Write ``cases`` as JSONL (sorted by id, sorted keys, UTF-8, LF), creating parent folders.

    Atomic: a temp file in the same folder is fsynced and renamed over ``path``, so a reader or a
    crash never sees a half-written split.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(_dump(c.model_dump(mode="json")) + "\n" for c in sorted(cases, key=_by_id))
    name = path.parent / f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    # O_CREAT with 0o666 gives the normal umask-based mode (0o664 under umask 0o002), unlike mkstemp
    descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            if path.is_file():
                os.fchmod(handle.fileno(), stat.S_IMODE(path.stat().st_mode))  # keep its mode
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        name.replace(path)
    except BaseException:
        name.unlink(missing_ok=True)
        raise
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)  # make the rename itself durable
    finally:
        os.close(directory)


def _by_id(case: TestCase) -> str:
    return case.id


def _dump(row: dict[str, object]) -> str:
    return json.dumps(row, sort_keys=True, ensure_ascii=False, separators=(", ", ": "))

"""Local dataset directories: ``datasets/<name>/<version>/<split>.jsonl`` + manifest (T1.10 S1).

The files are untrusted input: regular files only (no symlink), every line is read with a size
cap, parsing is linear, and errors name ``file:line`` but never quote the row.
"""

import os
import stat
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from pydantic import ValidationError

from pruefstand.core.config.gate import redact_key
from pruefstand.core.enums import Split
from pruefstand.core.errors import ConfigError, DatasetError
from pruefstand.core.models.dataset import DatasetManifest
from pruefstand.core.models.testcase import TestCase

MAX_LINE_BYTES = 1_000_000
"""Longest accepted line of a split file."""
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_BYTES = 1_000_000
MAX_CASES = 500_000
_DETAIL_CHARS = 200
_MAX_DETAILS = 3
MANIFEST_FILE = "dataset_manifest.json"


@dataclass(frozen=True)
class Dataset:
    """A loaded dataset version: identity, corpus version and the cases of the chosen splits."""

    name: str
    version: str
    corpus_version: str
    cases: tuple[TestCase, ...]


def _open_regular(path: Path) -> BinaryIO:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        msg = f"{path}: cannot open (must be a regular file, not a symlink): {exc.strerror}"
        raise DatasetError(msg) from exc
    handle = os.fdopen(fd, "rb")
    if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
        handle.close()
        msg = f"{path}: not a regular file"
        raise DatasetError(msg)
    return handle


def read_manifest(directory: Path) -> DatasetManifest:
    """Read and validate ``dataset_manifest.json`` of ``directory``.

    Args:
        directory: A dataset version directory.

    Returns:
        The manifest.

    Raises:
        DatasetError: The file is missing, not a regular file, larger than 1 MB or invalid.
    """
    path = directory / MANIFEST_FILE
    if not path.exists() and not path.is_symlink():
        msg = f"{path}: missing {MANIFEST_FILE}"
        raise DatasetError(msg)
    with _open_regular(path) as handle:
        raw = handle.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        msg = f"{path}: larger than {MAX_MANIFEST_BYTES} bytes"
        raise DatasetError(msg)
    try:
        return DatasetManifest.model_validate_json(raw)
    except ValidationError as exc:
        msg = f"{path}: {_describe(exc)}"
        raise DatasetError(msg) from exc


def _describe(exc: ValidationError) -> str:
    """Field paths and reasons only: never the offending value (it may hold a secret)."""
    parts = []
    for err in exc.errors(include_url=False, include_input=False)[:_MAX_DETAILS]:
        loc = [str(p) for p in err["loc"]]
        if err["type"] == "extra_forbidden" and loc:
            loc[-1] = redact_key(loc[-1])
        parts.append(f"{'.'.join(loc) or '<row>'}: {str(err['msg'])[:_DETAIL_CHARS]}")
    return "; ".join(parts)


def _lines(path: Path) -> list[tuple[int, bytes]]:
    """Return ``(line number, bytes)`` of the non-blank lines, refusing over-long ones."""
    found: list[tuple[int, bytes]] = []
    total = 0
    with _open_regular(path) as handle:
        number = 0
        while chunk := handle.readline(MAX_LINE_BYTES + 1):
            number += 1
            total += len(chunk)
            unterminated = len(chunk) > MAX_LINE_BYTES and not chunk.endswith(b"\n")
            if unterminated or total > MAX_FILE_BYTES:
                msg = f"{path}:{number}: line too long (limit {MAX_LINE_BYTES} bytes)"
                if total > MAX_FILE_BYTES:
                    msg = f"{path}: larger than {MAX_FILE_BYTES} bytes"
                raise DatasetError(msg)
            if chunk.strip():
                found.append((number, chunk))
            if len(found) > MAX_CASES:
                msg = f"{path}: more than {MAX_CASES} cases"
                raise DatasetError(msg)
    return found


def _row(path: Path, number: int, raw: bytes) -> TestCase:
    try:
        return TestCase.model_validate_json(raw)
    except ValidationError as exc:
        msg = f"{path}:{number}: {_describe(exc)}"
        raise DatasetError(msg) from exc


def _load_split(
    directory: Path, split: Split, manifest: DatasetManifest, seen: set[str]
) -> list[TestCase]:
    path = directory / f"{split.value}.jsonl"
    if not path.exists() and not path.is_symlink():
        msg = f"{path}: split file {split.value}.jsonl is missing"
        raise DatasetError(msg)
    cases: list[TestCase] = []
    for number, raw in _lines(path):
        case = _row(path, number, raw)
        if case.split is not split:
            msg = f"{path}:{number}: split is {case.split.value!r}, the file holds {split.value!r}"
            raise DatasetError(msg)
        if case.corpus_version != manifest.corpus_version:
            msg = f"{path}:{number}: corpus_version differs from {MANIFEST_FILE}"
            raise DatasetError(msg)
        if case.id in seen:
            msg = f"{path}:{number}: duplicate case id {case.id!r}"
            raise DatasetError(msg)
        seen.add(case.id)
        cases.append(case)
    expected = manifest.splits.get(split)
    if expected is not None and expected != len(cases):
        msg = f"{path}: {len(cases)} cases, but {MANIFEST_FILE} says {expected}"
        raise DatasetError(msg)
    return cases


def _directory(dataset: str) -> Path:
    if dataset.startswith("hf://"):
        msg = "hf:// datasets arrive in T4.7b"
        raise ConfigError(msg)
    directory = Path(dataset)
    if not directory.is_dir():
        msg = f"{dataset}: not a directory (expected datasets/<name>/<version>/)"
        raise DatasetError(msg)
    return directory


def load_dataset(dataset: str, splits: Sequence[Split]) -> Dataset:
    """Load and validate the cases of ``splits`` from a local dataset directory.

    Args:
        dataset: Path of ``datasets/<name>/<version>/`` (``hf://`` is not supported yet).
        splits: Splits to load; the cases come back in this order, file order within a split.

    Returns:
        The dataset with name, version and corpus version taken from its manifest.

    Raises:
        ConfigError: ``dataset`` is an ``hf://`` reference.
        DatasetError: A file or the manifest is missing or invalid, a row fails validation
            (the message names ``file:line``), a row's split or ``corpus_version`` disagrees with
            its file or the manifest, a case id repeats, or a count differs from the manifest.
    """
    directory = _directory(dataset)
    manifest = read_manifest(directory)
    cases: list[TestCase] = []
    seen: set[str] = set()
    for split in dict.fromkeys(splits):
        cases.extend(_load_split(directory, split, manifest, seen))
    return Dataset(manifest.name, manifest.version, manifest.corpus_version, tuple(cases))


def load_cases(dataset: str, splits: Sequence[Split]) -> tuple[str, str, list[TestCase]]:
    """Return ``(name, version, cases)`` of ``splits``; see ``load_dataset`` for the rules.

    Args:
        dataset: Path of ``datasets/<name>/<version>/``.
        splits: Splits to load.

    Returns:
        Dataset name, dataset version and the validated cases.

    Raises:
        ConfigError: ``dataset`` is an ``hf://`` reference (arrives in T4.7b).
        DatasetError: See ``load_dataset``.
    """
    loaded = load_dataset(dataset, splits)
    return loaded.name, loaded.version, list(loaded.cases)


def check_dataset(dataset: str) -> Dataset:
    """Load every split listed in the manifest (``pruefstand validate dataset``).

    Args:
        dataset: Path of the dataset version directory.

    Returns:
        The dataset with all cases.

    Raises:
        ConfigError: ``dataset`` is an ``hf://`` reference.
        DatasetError: See ``load_dataset``.
    """
    manifest = read_manifest(_directory(dataset))
    return load_dataset(dataset, tuple(manifest.splits))

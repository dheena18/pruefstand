"""``index.json``: per ``(fingerprint, ref)`` the ordered promoted runs, newest last (X2.7, D157).

The private ``baselines`` branch holds only this file. Fingerprints, refs and run ids come from
data, so every key is validated against a strict charset before it can become a path component.
"""

import json
import re
from pathlib import Path
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError

from pruefstand.core.errors import StoreError
from pruefstand.store._run_files import read_bounded
from pruefstand.store._safe_error import safe_error

REFS = (
    "main",
    "nightly-b0",
    "nightly-b1",
    "nightly-b2",
    "release-b0",
    "release-b1",
    "release-b2",
)
"""The only refs a baseline can have (ADR-0004, R13 D305); any other ref is a ``StoreError``."""
MAX_INDEX_BYTES = 4 * 1024 * 1024
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_FINGERPRINT = re.compile(r"[0-9a-f]{16}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _shown(value: object) -> str:
    text = repr(value)
    return text if len(text) <= 48 else text[:45] + "..."


def validate_fingerprint(value: str) -> str:
    """Return ``value`` if it is a safe path component for a fingerprint.

    Raises:
        StoreError: Not 16 lowercase hex characters (the output of ``stable_hash``).
    """
    if _FINGERPRINT.fullmatch(value) is None:
        msg = f"invalid eval fingerprint {_shown(value)}: expected 16 lowercase hex characters"
        raise StoreError(msg)
    return value


def validate_run_id(value: str) -> str:
    """Return ``value`` if it is a safe path component for a run id.

    Raises:
        StoreError: Not 1..64 characters of ``[A-Za-z0-9_-]`` starting with a letter or digit.
    """
    if _NAME.fullmatch(value) is None:
        msg = f"invalid run id {_shown(value)}: use 1..64 of [A-Za-z0-9_-]"
        raise StoreError(msg)
    return value


def validate_ref(value: str) -> str:
    """Return ``value`` if it is one of ``REFS``.

    Raises:
        StoreError: Any other ref, including ``release``.
    """
    if value not in REFS:
        msg = f"invalid ref {_shown(value)}: use one of {', '.join(REFS)}"
        raise StoreError(msg)
    return value


class IndexEntry(BaseModel):
    """One promotion of a run to a ref."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    manifest_sha256: str
    promoted_at: AwareDatetime
    git_sha: str | None = None


class RefEntry(BaseModel):
    """The promotions of one ref, oldest first; the last one is the current baseline."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    runs: tuple[IndexEntry, ...]


class BaselineIndex(BaseModel):
    """The content of ``baselines/index.json``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    entries: dict[str, dict[str, RefEntry]]

    @classmethod
    def empty(cls) -> Self:
        """An index without any baseline."""
        return cls(entries={})


def parse_index(data: bytes) -> BaselineIndex:
    """Parse and validate ``index.json`` bytes.

    Args:
        data: The file content.

    Returns:
        The index.

    Raises:
        StoreError: Larger than ``MAX_INDEX_BYTES``, not a valid index, or a key that is not a
            safe fingerprint, ref or run id. Messages never contain text from the file.
    """
    if len(data) > MAX_INDEX_BYTES:
        msg = f"the baseline index is larger than the {MAX_INDEX_BYTES} byte limit"
        raise StoreError(msg)
    try:
        index = BaselineIndex.model_validate_json(data)
    except ValidationError as exc:
        msg = f"cannot read the baseline index: {safe_error(exc)}"
        raise StoreError(msg) from exc
    for fingerprint, refs in index.entries.items():
        validate_fingerprint(fingerprint)
        for ref, entry in refs.items():
            validate_ref(ref)
            for run in entry.runs:
                validate_run_id(run.run_id)
                if _SHA256.fullmatch(run.manifest_sha256) is None:
                    msg = "the baseline index holds an invalid manifest sha256"
                    raise StoreError(msg)
    return index


def render_index(index: BaselineIndex) -> bytes:
    """Serialise ``index``: indent 2, sorted keys, UTF-8, final newline (stable diffs)."""
    text = json.dumps(index.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


def with_promotion(
    index: BaselineIndex, fingerprint: str, ref: str, entry: IndexEntry
) -> BaselineIndex:
    """Return ``index`` with ``entry`` as the newest run of ``(fingerprint, ref)``.

    An earlier entry of the same run id is replaced (a re-promotion).

    Args:
        index: The current index (unchanged).
        fingerprint: Validated ``eval_fingerprint``.
        ref: Validated ref.
        entry: The promotion.

    Returns:
        A new index.
    """
    refs = dict(index.entries.get(fingerprint, {}))
    runs = tuple(r for r in refs.get(ref, RefEntry(runs=())).runs if r.run_id != entry.run_id)
    refs[ref] = RefEntry(runs=(*runs, entry))
    return index.model_copy(update={"entries": {**index.entries, fingerprint: refs}})


def reconcile_index(index: BaselineIndex, root: Path) -> BaselineIndex:
    """Drop what the data root no longer has (after a prune).

    A ref whose directory is gone disappears with its runs; of the remaining runs only the current
    one (the last) and those with a ``history/<run_id>`` directory stay; a fingerprint without refs
    disappears.

    Args:
        index: The index.
        root: The data root (``<root>/<fingerprint>/<ref>`` and ``/history/<run_id>``).

    Returns:
        A new index.
    """
    entries: dict[str, dict[str, RefEntry]] = {}
    for fingerprint, refs in index.entries.items():
        kept: dict[str, RefEntry] = {}
        for ref, entry in refs.items():
            if not (root / fingerprint / ref).is_dir() or not entry.runs:
                continue
            *older, current = entry.runs
            alive = [r for r in older if (root / fingerprint / "history" / r.run_id).is_dir()]
            kept[ref] = RefEntry(runs=(*alive, current))
        if kept:
            entries[fingerprint] = kept
    return index.model_copy(update={"entries": entries})


def read_index_file(path: Path) -> BaselineIndex:
    """Read ``baselines/index.json`` from a checkout (bounded, no symlinks).

    Raises:
        StoreError: Missing, special, too large or invalid.
    """
    return parse_index(read_bounded(path, MAX_INDEX_BYTES))

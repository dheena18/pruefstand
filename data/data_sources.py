"""Source model, loader, hashing and errors of the data downloader (T2.1).

``data/sources.yaml`` is the committed pin list. Per-kind ``defaults`` are merged into each
entry; ``files`` maps a file name (relative to the source directory) to its SHA-256, or to
``None`` while the pin is still missing (``--update-pins`` fills it).
"""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

KINDS = ("gii", "hf", "eurlex", "github")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
CHUNK = 1 << 20
SOURCES_HEADER = (
    "# Pinned source list of the data downloader (T2.1). Machine-managed by\n"
    "# `python data/download.py --update-pins`; edit by hand only to add a source.\n"
)


class DataError(Exception):
    """Base class of downloader failures; ``exit_code`` is the process exit code."""

    exit_code = 1


class ChecksumError(DataError):
    """A file's SHA-256 differs from the pin."""

    def __init__(self, source_id: str, name: str, expected: str, actual: str) -> None:
        super().__init__(
            f"checksum mismatch: {source_id}/{name} expected {expected} actual {actual}"
        )


class LicenseMismatch(DataError):  # noqa: N818  # name fixed by the T2.1 prompt (exit 3)
    """The licence found upstream differs from sources.yaml."""

    exit_code = 3

    def __init__(self, source_id: str, expected: str, actual: str) -> None:
        super().__init__(
            f"license mismatch: {source_id}: sources.yaml says {expected!r}, upstream: {actual!r}"
        )


class ConfigMissingError(DataError):
    """The pinned Hugging Face config does not exist in the dataset."""

    exit_code = 2

    def __init__(self, source_id: str, config: str, available: list[str]) -> None:
        super().__init__(
            f"config missing: {source_id} has no config {config!r}; available: {sorted(available)}"
        )


class FetchError(DataError):
    """A download failed (HTTP error, bot challenge, missing file after download)."""


class SourcesError(DataError):
    """``sources.yaml`` is malformed."""


@dataclass
class SyncResult:
    """Outcome of syncing one source: computed hashes, download count, names without a pin."""

    files: dict[str, str] = field(default_factory=dict)
    downloads: int = 0
    unpinned: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Source:
    """One pinned source. Unused fields stay ``None`` for kinds that do not need them."""

    id: str
    kind: str
    license: str
    license_config: str
    redistribute: bool
    attribution: str
    files: dict[str, str | None]
    abbrev: str | None = None
    slug: str | None = None
    celex: str | None = None
    pinned: str | None = None
    repo_id: str | None = None
    config: str | None = None
    revision: str | None = None
    ref: str | None = None
    repo: str | None = None
    commit: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def rel_dir(self) -> str:
        """Directory below ``data/raw`` (``gii/kschg``, ``eurlex/<celex>``, ``hf/<id>``, ...)."""
        if self.kind in ("gii", "eurlex"):
            return self.id.replace(":", "/")
        return f"{self.kind}/{self.id}"

    @property
    def pin(self) -> str:
        """Pinned version for the manifest: revision SHA, commit SHA or download date."""
        return self.revision or self.commit or self.pinned or ""


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of a file, read in 1 MiB chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _build(raw: dict[str, Any], defaults: dict[str, Any]) -> Source:
    merged = {**defaults, **raw}
    known = set(Source.__dataclass_fields__) - {"extra"}
    extra = {k: v for k, v in merged.items() if k not in known}
    fields = {k: v for k, v in merged.items() if k in known}
    try:
        files = {str(k): (None if v is None else str(v)) for k, v in fields.pop("files").items()}
        source = Source(files=files, extra=extra, **fields)
    except (KeyError, TypeError, AttributeError) as err:
        msg = f"bad entry {raw.get('id')!r}: {err}"
        raise SourcesError(msg) from err
    _validate(source)
    return source


def _validate(source: Source) -> None:
    if source.kind not in KINDS:
        msg = f"{source.id}: unknown kind {source.kind!r}"
        raise SourcesError(msg)
    if source.kind == "hf" and not (source.revision and HEX40.match(source.revision)):
        msg = f"{source.id}: hf revision must be a 40-hex commit SHA"
        raise SourcesError(msg)
    if source.kind == "github" and not (source.commit and HEX40.match(source.commit)):
        msg = f"{source.id}: github commit must be a 40-hex SHA"
        raise SourcesError(msg)
    for name, sha in source.files.items():
        if name.startswith("/") or ".." in Path(name).parts:
            msg = f"{source.id}: file name {name!r} must be relative without .."
            raise SourcesError(msg)
        if sha is not None and not HEX64.match(sha):
            msg = f"{source.id}/{name}: sha256 must be 64 lowercase hex characters"
            raise SourcesError(msg)


def load_raw(path: Path) -> dict[str, Any]:
    """Parse ``sources.yaml`` into its raw mapping."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
        msg = f"{path}: expected a mapping with a 'sources' list"
        raise SourcesError(msg)
    return data


def load_sources(path: Path) -> list[Source]:
    """Load, merge per-kind defaults and validate every source.

    Args:
        path: ``data/sources.yaml``.

    Returns:
        Sources in file order.

    Raises:
        SourcesError: Malformed entry, unknown kind, bad revision or checksum.
    """
    data = load_raw(path)
    defaults: dict[str, dict[str, Any]] = data.get("defaults") or {}
    sources = [_build(raw, defaults.get(raw.get("kind", ""), {})) for raw in data["sources"]]
    ids = [s.id for s in sources]
    if len(ids) != len(set(ids)):
        msg = "duplicate source ids in sources.yaml"
        raise SourcesError(msg)
    return sources


def save_pins(path: Path, updates: dict[str, dict[str, Any]]) -> None:
    """Rewrite ``sources.yaml`` with new ``files`` / ``revision`` / ``pinned`` values.

    Args:
        path: ``data/sources.yaml``.
        updates: ``{source_id: {"files": {...}, "revision": ..., "pinned": ...}}``; only the
            given keys of each entry change.
    """
    data = load_raw(path)
    for entry in data["sources"]:
        entry.update(updates.get(entry["id"], {}))
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)
    path.write_text(SOURCES_HEADER + body, encoding="utf-8")

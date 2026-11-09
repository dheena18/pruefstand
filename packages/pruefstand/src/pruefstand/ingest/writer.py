"""Deterministic corpus files (T2.5): ``write_corpus`` and the manifest it writes.

Layout (interfaces §1.2): ``<out_dir>/<tenant>.chunks.jsonl`` (one ``Chunk`` per line, sorted by
``(doc_id, chunk_id)``, sorted keys, compact JSON, UTF-8) and ``<out_dir>/manifest.json``. The
same chunks always produce the same bytes, so the same ``corpus_version``: no clock, no random
order, and ``created_at`` is midnight UTC of the version's date.

Tenant isolation is checked here too, as the last line of defence before the files exist: tenant
ids must be safe file names, a ``doc_id`` belongs to one tenant, a ``chunk_id`` occurs once.
"""

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pruefstand.core.errors import DatasetError
from pruefstand.core.fingerprint import corpus_version as compute_corpus_version
from pruefstand.core.ids import ChunkId, DocId, TenantId
from pruefstand.core.models.corpus import Chunk, CorpusManifest
from pruefstand.ingest.corpus_files import (
    MANIFEST_NAME,
    check_chunk_rules,
    created_at,
    file_sha256,
    tenant_file,
)

_LINE_SEPARATORS = {chr(code): f"\\u{code:04x}" for code in (0x2028, 0x2029, 0x0085)}
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class RenderedCorpus:
    """The serialised corpus: file name to bytes, and the chunk count per tenant."""

    files: dict[str, bytes]
    counts: dict[TenantId, int]


def serialise_chunk(chunk: Chunk) -> bytes:
    r"""Return the JSON line of ``chunk``: sorted keys, UTF-8, ending in ``\n``.

    ``U+2028``, ``U+2029`` and ``U+0085`` are written as escapes, so a reader that splits lines
    with ``str.splitlines()`` sees exactly one record per line.

    Args:
        chunk: The chunk.

    Returns:
        The line as bytes.

    Raises:
        DatasetError: The text holds a lone surrogate and cannot be encoded as UTF-8.
    """
    text = json.dumps(
        chunk.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    for char, escape in _LINE_SEPARATORS.items():
        text = text.replace(char, escape)
    try:
        return (text + "\n").encode("utf-8")
    except UnicodeEncodeError as exc:
        msg = f"chunk {chunk.chunk_id}: the text is not valid Unicode (lone surrogate)"
        raise DatasetError(msg) from exc


def render_corpus(chunks: Iterable[Chunk]) -> RenderedCorpus:
    """Validate and serialise ``chunks`` into one sorted file per tenant.

    Args:
        chunks: All chunks of the corpus in any order.

    Returns:
        The file contents and the counts.

    Raises:
        DatasetError: A tenant id is unsafe, a licence or source is empty or banned, a
            ``chunk_id`` occurs twice, or a ``doc_id`` has chunks in two tenants.
    """
    rows: dict[TenantId, list[tuple[DocId, ChunkId, bytes]]] = {}
    seen: set[ChunkId] = set()
    owner: dict[DocId, TenantId] = {}
    for chunk in chunks:
        check_chunk_rules(chunk)
        if chunk.chunk_id in seen:
            msg = f"chunk {chunk.chunk_id}: occurs twice"
            raise DatasetError(msg)
        seen.add(chunk.chunk_id)
        if owner.setdefault(chunk.doc_id, chunk.tenant) != chunk.tenant:
            first = owner[chunk.doc_id]
            msg = f"document {chunk.doc_id} has chunks in tenants {first!r} and {chunk.tenant!r}"
            raise DatasetError(msg)
        rows.setdefault(chunk.tenant, []).append(
            (chunk.doc_id, chunk.chunk_id, serialise_chunk(chunk))
        )
    files = {
        tenant_file(tenant): b"".join(line for _, _, line in sorted(rows[tenant], key=_sort_key))
        for tenant in sorted(rows)
    }
    return RenderedCorpus(files, {tenant: len(rows[tenant]) for tenant in sorted(rows)})


def _sort_key(row: tuple[DocId, ChunkId, bytes]) -> tuple[str, str]:
    return (row[0], row[1])


def _manifest(
    rendered: RenderedCorpus, sources: Mapping[str, str], version: str, when: datetime
) -> CorpusManifest:
    return CorpusManifest(
        corpus_version=version,
        created_at=when,
        sources=dict(sorted(sources.items())),
        tenants=rendered.counts,
        sha256={name: hashlib.sha256(data).hexdigest() for name, data in rendered.files.items()},
    )


def provisional_manifest(chunks: Iterable[Chunk], sources: Mapping[str, str]) -> CorpusManifest:
    """Build the manifest without a version, to compute ``corpus_version`` from it.

    Args:
        chunks: All chunks of the corpus.
        sources: Source id to pinned version (``{"gii:kschg": "2026-10-31"}``).

    Returns:
        A manifest with an empty ``corpus_version`` (the version is derived from the rest).

    Raises:
        DatasetError: See :func:`render_corpus`.
    """
    return _manifest(render_corpus(chunks), sources, "", _EPOCH)


def manifest_bytes(manifest: CorpusManifest) -> bytes:
    """Return ``manifest.json`` as canonical bytes (sorted keys, two-space indent, newline)."""
    text = json.dumps(
        manifest.model_dump(mode="json"), sort_keys=True, indent=2, ensure_ascii=False
    )
    return (text + "\n").encode("utf-8")


def write_corpus(
    chunks: Iterable[Chunk],
    out_dir: Path,
    corpus_version: str,
    *,
    sources: Mapping[str, str] | None = None,
) -> CorpusManifest:
    """Write the tenant files and ``manifest.json`` into ``out_dir``.

    The files are written to a staging directory next to ``out_dir``, their hashes are checked
    after writing, and the directory is renamed into place, so ``out_dir`` never holds a half
    written corpus. A corpus version is immutable: if ``out_dir`` exists it must hold exactly
    these bytes (then nothing changes), otherwise the call fails. Every call stages in a directory
    of its own (``.<version>.<random>.partial``), so concurrent ingests of one version do not share
    files and the loser of the final rename compares with the winner's bytes. A killed run leaves
    its ``.<version>.<random>.partial`` directory behind; it is safe to delete by hand.

    Args:
        chunks: All chunks of the corpus in any order.
        out_dir: ``corpus/<corpus_version>``; neither it nor its parent may be a symlink.
        corpus_version: ``fingerprint.corpus_version(provisional_manifest(...), date)``; checked
            against the content.
        sources: Source id to pinned version for the manifest.

    Returns:
        The manifest that was written.

    Raises:
        DatasetError: Invalid chunks (see :func:`render_corpus`), a malformed or wrong
            ``corpus_version``, a symlinked output path, an existing directory with different
            content, or a file whose hash differs after writing.
    """
    rendered = render_corpus(chunks)
    when = created_at(corpus_version)
    manifest = _manifest(rendered, sources or {}, corpus_version, when)
    expected = compute_corpus_version(manifest, corpus_version[:10])
    if expected != corpus_version:
        msg = f"corpus_version {corpus_version} does not match the content (expected {expected})"
        raise DatasetError(msg)
    _publish(Path(out_dir), {**rendered.files, MANIFEST_NAME: manifest_bytes(manifest)}, manifest)
    return manifest


def _publish(out_dir: Path, files: dict[str, bytes], manifest: CorpusManifest) -> None:
    parent = out_dir.parent
    if out_dir.is_symlink() or parent.is_symlink():
        msg = f"{out_dir}: the output directory and its parent must not be symlinks"
        raise DatasetError(msg)
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{out_dir.name}.", suffix=".partial", dir=parent))
    staging.chmod(0o755)  # mkdtemp makes it 0700; the published directory must be readable
    try:
        for name, data in files.items():
            _write_new(staging / name, data)
        _check_written(staging, manifest)
        _move_into_place(staging, out_dir, files)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _move_into_place(staging: Path, out_dir: Path, files: dict[str, bytes]) -> None:
    """Rename ``staging`` to ``out_dir``; an existing directory must hold the same bytes.

    Two ingests of the same version may run at once: each has its own staging directory, and
    when the other one wins the rename, the loser compares with what is there instead of failing.
    """
    if not out_dir.exists():
        try:
            staging.rename(out_dir)
        except OSError:
            if not out_dir.exists():
                raise
        else:
            return
    _same_as_existing(out_dir, files)


def _write_new(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o644)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _check_written(directory: Path, manifest: CorpusManifest) -> None:
    for name, digest in manifest.sha256.items():
        if file_sha256(directory / name) != digest:
            msg = f"{name}: sha256 differs after writing"
            raise DatasetError(msg)


def _same_as_existing(out_dir: Path, files: dict[str, bytes]) -> None:
    present = {p.name for p in out_dir.iterdir()} if out_dir.is_dir() else set()
    same = present == set(files) and all(
        file_sha256(out_dir / name) == hashlib.sha256(data).hexdigest()
        for name, data in files.items()
    )
    if not same:
        msg = f"{out_dir} already exists with different content; a corpus version is immutable"
        raise DatasetError(msg)

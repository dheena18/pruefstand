"""Integrity check of a written corpus directory (T2.5): ``verify_corpus``.

Used by ``scripts/validate_corpus.py`` and the tests. It trusts nothing in the directory: the
manifest is size-capped and parsed as ``CorpusManifest``, the file set must equal the manifest's
tenants, symlinks are refused, every line is parsed as a ``Chunk`` of the right tenant, and the
hashes, counts and ``corpus_version`` must agree.
"""

from pathlib import Path

from pydantic import ValidationError

from pruefstand.core.errors import DatasetError
from pruefstand.core.fingerprint import corpus_version as compute_corpus_version
from pruefstand.core.ids import ChunkId, DocId, TenantId
from pruefstand.core.models.corpus import Chunk, CorpusManifest
from pruefstand.ingest.corpus_files import (
    MANIFEST_NAME,
    MAX_MANIFEST_BYTES,
    checked_tenant,
    checked_version,
    file_sha256,
    iter_lines,
    read_regular,
    tenant_file,
)


def read_manifest(directory: Path) -> CorpusManifest:
    """Read and validate ``<directory>/manifest.json``.

    Raises:
        DatasetError: Missing, oversized or not a valid ``CorpusManifest``.
    """
    data = read_regular(directory / MANIFEST_NAME, MAX_MANIFEST_BYTES)
    try:
        return CorpusManifest.model_validate_json(data)
    except ValidationError as exc:
        msg = f"{MANIFEST_NAME}: not a valid corpus manifest ({exc.error_count()} errors)"
        raise DatasetError(msg) from exc


def _check_file_set(directory: Path, manifest: CorpusManifest) -> None:
    for tenant in manifest.tenants:
        checked_tenant(tenant, f"{MANIFEST_NAME}: tenant")
    wanted = {tenant_file(t) for t in manifest.tenants} | {MANIFEST_NAME}
    present = {p.name for p in directory.iterdir()}
    for name in sorted(present - wanted):
        msg = f"{name}: not listed in the manifest"
        raise DatasetError(msg)
    for name in sorted(wanted - present):
        msg = f"{name}: listed in the manifest but missing"
        raise DatasetError(msg)
    if set(manifest.sha256) != wanted - {MANIFEST_NAME}:
        msg = f"{MANIFEST_NAME}: sha256 keys do not match the tenants"
        raise DatasetError(msg)


def _check_tenant_file(
    path: Path,
    tenant: TenantId,
    manifest: CorpusManifest,
    owner: dict[DocId, TenantId],
    seen: set[ChunkId],
) -> None:
    if file_sha256(path) != manifest.sha256[path.name]:
        msg = f"{path.name}: sha256 does not match the manifest"
        raise DatasetError(msg)
    count = 0
    for number, line in enumerate(iter_lines(path), start=1):
        try:
            chunk = Chunk.model_validate_json(line)
        except ValidationError as exc:
            msg = f"{path.name}:{number}: not a valid chunk ({exc.error_count()} errors)"
            raise DatasetError(msg) from exc
        if chunk.tenant != tenant:
            msg = f"{path.name}:{number}: chunk {chunk.chunk_id} has tenant {chunk.tenant!r}"
            raise DatasetError(msg)
        if chunk.chunk_id in seen or owner.setdefault(chunk.doc_id, tenant) != tenant:
            msg = f"{path.name}:{number}: chunk {chunk.chunk_id} or document {chunk.doc_id} repeats"
            raise DatasetError(msg)
        seen.add(chunk.chunk_id)
        count += 1
    if count != manifest.tenants[tenant]:
        msg = f"{path.name}: {count} lines, the manifest says {manifest.tenants[tenant]}"
        raise DatasetError(msg)


def verify_corpus(directory: Path) -> CorpusManifest:
    """Check a corpus directory against its manifest and return the manifest.

    Args:
        directory: ``corpus/<corpus_version>``; must not be a symlink and must be named like the
            manifest's ``corpus_version``.

    Returns:
        The validated manifest.

    Raises:
        DatasetError: Any inconsistency: extra or missing files, a symlink, a changed byte
            (sha256), a wrong line count, a chunk in the wrong tenant file, a repeated chunk or a
            document in two tenants, or a ``corpus_version`` that does not match the content.
    """
    if directory.is_symlink() or not directory.is_dir():
        msg = f"{directory}: not a directory (or a symlink)"
        raise DatasetError(msg)
    manifest = read_manifest(directory)
    checked_version(manifest.corpus_version)
    if directory.name != manifest.corpus_version:
        msg = f"{directory.name}: not named like the corpus_version {manifest.corpus_version}"
        raise DatasetError(msg)
    _check_file_set(directory, manifest)
    owner: dict[DocId, TenantId] = {}
    seen: set[ChunkId] = set()
    for tenant in manifest.tenants:
        _check_tenant_file(directory / tenant_file(tenant), tenant, manifest, owner, seen)
    expected = compute_corpus_version(manifest, manifest.corpus_version[:10])
    if expected != manifest.corpus_version:
        msg = f"corpus_version {manifest.corpus_version} does not match the content ({expected})"
        raise DatasetError(msg)
    return manifest

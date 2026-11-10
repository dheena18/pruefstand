"""Integrity check of a written corpus directory (T2.5): ``verify_corpus``.

Used by ``scripts/validate_corpus.py`` and the tests. It trusts nothing in the directory: the
manifest is size-capped and parsed as ``CorpusManifest``, the file set must equal the manifest's
tenants, symlinks are refused, every line is parsed as a ``Chunk`` of the right tenant, and the
hashes, counts and ``corpus_version`` must agree. The writer's own rules (licence, banned source,
sorted order) are checked again, and an optional tenant plan is compared with the chunks.
"""

import hashlib
from pathlib import Path

from pydantic import ValidationError

from pruefstand.core.config import TenantPlan
from pruefstand.core.errors import DatasetError
from pruefstand.core.fingerprint import corpus_version as compute_corpus_version
from pruefstand.core.ids import ChunkId, DocId, TenantId
from pruefstand.core.models.corpus import Chunk, CorpusManifest
from pruefstand.ingest.corpus_files import (
    MANIFEST_NAME,
    MAX_MANIFEST_BYTES,
    check_chunk_rules,
    checked_tenant,
    checked_version,
    iter_lines,
    read_regular,
    tenant_file,
)
from pruefstand.ingest.corpus_plan import PlanCheck


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


class _Pass:
    """The state of one verification: who owns which document, which chunks were seen."""

    def __init__(self, plan: PlanCheck | None) -> None:
        self.plan = plan
        self.owner: dict[DocId, TenantId] = {}
        self.seen: set[ChunkId] = set()


def _check_line(
    path: Path, number: int, line: bytes, tenant: TenantId, state: _Pass
) -> tuple[str, str]:
    """Check one chunk line; return its sort key ``(doc_id, chunk_id)``.

    Raises:
        DatasetError: Not a valid chunk, a rule of the writer is broken, wrong tenant, repeated
            chunk or document in two tenants, or a disagreement with the plan.
    """
    where = f"{path.name}:{number}"
    try:
        chunk = Chunk.model_validate_json(line)
    except ValidationError as exc:
        msg = f"{where}: not a valid chunk ({exc.error_count()} errors)"
        raise DatasetError(msg) from exc
    if chunk.tenant != tenant:
        msg = f"{where}: chunk {chunk.chunk_id} has tenant {chunk.tenant!r}"
        raise DatasetError(msg)
    if chunk.chunk_id in state.seen or state.owner.setdefault(chunk.doc_id, tenant) != tenant:
        msg = f"{where}: chunk {chunk.chunk_id} or document {chunk.doc_id} repeats"
        raise DatasetError(msg)
    state.seen.add(chunk.chunk_id)
    try:
        check_chunk_rules(chunk)
    except DatasetError as exc:
        msg = f"{where}: {exc}"
        raise DatasetError(msg) from exc
    problem = state.plan.problem(chunk) if state.plan is not None else None
    if problem is not None:
        msg = f"{where}: {problem}"
        raise DatasetError(msg)
    return chunk.doc_id, chunk.chunk_id


def _check_order(
    path: Path, number: int, previous: tuple[str, str] | None, key: tuple[str, str]
) -> None:
    if previous is not None and key < previous:
        msg = f"{path.name}:{number}: chunks are not sorted by (doc_id, chunk_id)"
        raise DatasetError(msg)


def _check_tenant_file(
    path: Path, tenant: TenantId, manifest: CorpusManifest, state: _Pass
) -> None:
    """Hash and parse the file in one pass; a changed byte is reported before a bad line."""
    digest = hashlib.sha256()
    failure: DatasetError | None = None
    previous: tuple[str, str] | None = None
    count = 0
    for number, line in enumerate(iter_lines(path), start=1):
        digest.update(line)
        count += 1
        if failure is not None:
            continue  # keep reading: the hash decides which problem is reported
        try:
            key = _check_line(path, number, line, tenant, state)
            _check_order(path, number, previous, key)
        except DatasetError as exc:
            failure = exc
            continue
        previous = key
    if digest.hexdigest() != manifest.sha256[path.name]:
        msg = f"{path.name}: sha256 does not match the manifest"
        raise DatasetError(msg)
    if failure is not None:
        raise failure
    if count != manifest.tenants[tenant]:
        msg = f"{path.name}: {count} lines, the manifest says {manifest.tenants[tenant]}"
        raise DatasetError(msg)


def verify_corpus(directory: Path, plan: TenantPlan | None = None) -> CorpusManifest:
    """Check a corpus directory against its manifest and return the manifest.

    Args:
        directory: ``corpus/<corpus_version>``; must not be a symlink and must be named like the
            manifest's ``corpus_version``.
        plan: Optional tenant plan (``corpus.yaml: plan``); chunks must then agree with it as far
            as a chunk shows it (see :mod:`pruefstand.ingest.corpus_plan`).

    Returns:
        The validated manifest.

    Raises:
        DatasetError: Any inconsistency: extra or missing files, a symlink, a changed byte
            (sha256), a wrong line count, a chunk in the wrong tenant file, a repeated chunk or a
            document in two tenants, a chunk the writer would have refused (empty licence, banned
            source), chunks out of order, a tenant that disagrees with ``plan``, or a
            ``corpus_version`` that does not match the content.
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
    state = _Pass(None if plan is None else PlanCheck(plan))
    for tenant in manifest.tenants:
        _check_tenant_file(directory / tenant_file(tenant), tenant, manifest, state)
    expected = compute_corpus_version(manifest, manifest.corpus_version[:10])
    if expected != manifest.corpus_version:
        msg = f"corpus_version {manifest.corpus_version} does not match the content ({expected})"
        raise DatasetError(msg)
    return manifest

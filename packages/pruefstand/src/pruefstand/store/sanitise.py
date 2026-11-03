"""``sanitise_run``: a copy of a run that may leave the VM (T6.1 S5, round 8 W2.9, D315).

Chunk text is removed, canary tokens and forbidden strings are masked, every case built from a
canary is dropped and ``infra_error`` is reduced to its kind. The original run is never changed.
``write_public_export`` writes the sanitised files and the ``manifest.json`` marker that
``push_dashboard_data`` requires; ``scored.jsonl`` (full case bodies) is never exported.
"""

import hashlib
import json
import re
import secrets
import shutil
from collections.abc import Callable
from pathlib import Path

import polars as pl

from pruefstand.core.errors import StoreError
from pruefstand.core.models.attacks import CanaryRegistry
from pruefstand.core.models.run import RunArtifacts, RunManifest, RunResults, ScoredCase
from pruefstand.core.models.target import CaseRecord, TargetResponse
from pruefstand.core.models.testcase import TestCase
from pruefstand.store._run_files import manifest_text, read_manifest, results_frame
from pruefstand.store._run_render import render_files

REDACTED = "‹redacted›"  # noqa: RUF001  (the mask fixed by the T6.1 prompt)
PUBLISHED_FILES = ("run.json", "results.parquet", "responses.jsonl")
_CANARY_PREFIX = re.compile(rb"canary-", re.IGNORECASE)
_MIN_REVERSE_MATCH = 6


class _Masker:
    """Masks the strings of a registry and of the forbidden strings of a run, case-insensitively."""

    def __init__(self, canaries: CanaryRegistry, cases: list[TestCase]) -> None:
        self.canary_texts = sorted(
            {
                text
                for c in canaries.canaries
                for text in (c.token, c.fact, c.forbidden_answer)
                if text
            },
            key=len,
            reverse=True,
        )
        self.questions = {
            c.probe_question.casefold() for c in canaries.canaries if c.probe_question
        }
        every = {*self.canary_texts, *(s for case in cases for s in case.forbidden_strings if s)}
        ordered = sorted(every, key=len, reverse=True)
        self._pattern = re.compile("|".join(re.escape(t) for t in ordered), re.IGNORECASE)
        self._canary = re.compile("|".join(re.escape(t) for t in self.canary_texts), re.IGNORECASE)

    def mask(self, text: str) -> str:
        return self._pattern.sub(REDACTED, text)

    def is_canary_case(self, case: TestCase) -> bool:
        """A case whose forbidden strings contain a canary, or whose question is its probe."""
        if case.question.strip().casefold() in self.questions:
            return True
        for forbidden in case.forbidden_strings:
            if self._canary.search(forbidden):
                return True
            low = forbidden.casefold()
            if len(forbidden) >= _MIN_REVERSE_MATCH and any(
                low in t.casefold() for t in self.canary_texts
            ):
                return True
        return False


def text_masker(run: RunArtifacts, canaries: CanaryRegistry) -> Callable[[str], str]:
    """Return a function that masks the canaries and forbidden strings of ``run`` in any text.

    ``export-dashboard`` (T8.1) uses it for text that ``sanitise_run`` does not touch, such as the
    hard-fail evidence of ``gate.json`` (D542).

    Args:
        run: The unsanitised run (its cases supply the forbidden strings).
        canaries: The registry.

    Returns:
        A function from text to text; every match becomes ``REDACTED``.
    """
    return _Masker(canaries, [s.case for s in run.results.values]).mask


def sanitise_run(run: RunArtifacts, canaries: CanaryRegistry) -> RunArtifacts:
    """Return a copy of ``run`` that is safe for the public dashboard-data repo.

    Chunk ``text`` is emptied (ids, doc ids, scores and ranks stay). Every canary token and fact,
    every canary ``forbidden_answer`` and every ``forbidden_strings`` value of the run is masked as
    the ``REDACTED`` mask (case-insensitively) in answers, citations, errors, case bodies and metric
    details. A case whose ``forbidden_strings`` contain a canary, or whose question is a canary
    probe question, is dropped with its record and values. ``infra_error`` is reduced to its kind
    (D315) and ``artifact_sha256`` is cleared.

    Args:
        run: The run read from its run directory (callers pass public + held-out canaries merged).
        canaries: The registry; an empty one is refused.

    Returns:
        A new ``RunArtifacts`` with the same root; ``run`` is unchanged.

    Raises:
        StoreError: ``canaries`` holds no canary.
    """
    if not canaries.canaries:
        msg = "the canary registry is empty; refusing to sanitise without one"
        raise StoreError(msg)
    results = run.results
    masker = _Masker(canaries, [s.case for s in results.values])
    dropped = {s.case.id for s in results.values if masker.is_canary_case(s.case)}
    values = tuple(_scored(s, masker) for s in results.values if s.case.id not in dropped)
    records = tuple(_record(r, masker) for r in results.records if r.case_id not in dropped)
    old = results.manifest
    kind = old.infra_error.split(":", 1)[0].strip() if old.infra_error else None
    manifest = old.model_copy(
        update={"infra_error": kind, "n_cases": len(values), "artifact_sha256": {}}
    )
    clean = RunResults(manifest=manifest, records=records, values=values)
    return RunArtifacts(results=clean, root=run.root)


def _scored(scored: ScoredCase, masker: _Masker) -> ScoredCase:
    case = scored.case.model_copy(
        update={
            "question": masker.mask(scored.case.question),
            "reference_answer": _opt(scored.case.reference_answer, masker),
            "evidence_span": _opt(scored.case.evidence_span, masker),
            "forbidden_strings": tuple(REDACTED for _ in scored.case.forbidden_strings),
        }
    )
    values = tuple(
        v.model_copy(update={"details": {k: _mask_detail(x, masker) for k, x in v.details.items()}})
        for v in scored.values
    )
    return ScoredCase(case=case, values=values)


def _mask_detail(value: object, masker: _Masker) -> object:
    return masker.mask(value) if isinstance(value, str) else value


def _opt(text: str | None, masker: _Masker) -> str | None:
    return None if text is None else masker.mask(text)


def _record(record: CaseRecord, masker: _Masker) -> CaseRecord:
    request = record.request.model_copy(update={"question": masker.mask(record.request.question)})
    return record.model_copy(
        update={
            "request": request,
            "response": _response(record.response, masker),
            "error": _opt(record.error, masker),
        }
    )


def _response(response: TargetResponse | None, masker: _Masker) -> TargetResponse | None:
    if response is None:
        return None
    chunks = None
    if response.chunks is not None:
        chunks = tuple(c.model_copy(update={"text": ""}) for c in response.chunks)
    return response.model_copy(
        update={
            "answer": masker.mask(response.answer),
            "citations": tuple(masker.mask(c) for c in response.citations),
            "chunks": chunks,
        }
    )


def write_public_export(run: RunArtifacts, out: Path) -> Path:
    """Write the files of a sanitised run into the new directory ``out``.

    The directory holds ``run.json``, ``results.parquet`` (13 columns, no answers),
    ``responses.jsonl`` (masked answers, no chunk text) and ``manifest.json`` with
    ``"sanitised": true`` and the SHA-256 of each file. It is written to a hidden sibling and
    renamed, so nothing is left behind when a check fails.

    Args:
        run: The result of ``sanitise_run``.
        out: A directory that does not exist yet.

    Returns:
        ``out``.

    Raises:
        StoreError: ``out`` exists, a file would contain ``CANARY-`` (the registry missed a
            canary), or a write failed.
    """
    if out.exists() or out.is_symlink():
        msg = f"export directory {out} exists; choose a new one"
        raise StoreError(msg)
    try:
        files = render_files(run.results)
        files.pop("scored.jsonl")
        manifest = run.results.manifest.model_copy(
            update={
                "artifact_sha256": {
                    n: hashlib.sha256(files[n]).hexdigest()
                    for n in ("results.parquet", "responses.jsonl")
                }
            }
        )
        files["run.json"] = manifest_text(manifest).encode("utf-8")
        _refuse_canaries(files, results_frame(run.results.values))
    except (ValueError, pl.exceptions.PolarsError) as exc:
        msg = f"cannot render the public export: {type(exc).__name__}"
        raise StoreError(msg) from exc
    return _write_dir(out, files, manifest.run_id)


def _refuse_canaries(files: dict[str, bytes], frame: pl.DataFrame) -> None:
    """Fail closed when any text that will be published still names a canary."""
    flat = frame.with_columns(pl.col("tags").list.join(" "))
    texts = [*files.values(), flat.write_csv().encode("utf-8")]
    if any(_CANARY_PREFIX.search(t) for t in texts):
        msg = "refusing to export: the sanitised run still contains 'CANARY-' (unknown canary?)"
        raise StoreError(msg)


def _write_dir(out: Path, files: dict[str, bytes], run_id: str) -> Path:
    tmp = out.parent / f".{out.name}.{secrets.token_hex(4)}.tmp"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp.mkdir()
        for name, data in files.items():
            (tmp / name).write_bytes(data)
        _write_marker(tmp, run_id)
        Path(tmp).rename(out)
    except OSError as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        msg = f"cannot write the public export {out}: {exc}"
        raise StoreError(msg) from exc
    return out


def _write_marker(directory: Path, run_id: str) -> None:
    files = {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    }
    document = {"schema_version": "1", "sanitised": True, "run_id": run_id, "files": files}
    text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    (directory / "manifest.json").write_text(text, encoding="utf-8")


def seal_export(directory: Path) -> None:
    """Rewrite ``manifest.json`` of an export directory after files were added to it.

    ``export-dashboard`` (T8.1) adds ``gate.json``, ``slices.json``, ``report.html`` and case
    shards; the manifest then lists every regular file with its SHA-256. This is a guard against
    accidents (a half-written export), not against a hostile writer.

    Args:
        directory: A directory written by ``write_public_export`` (it must hold ``run.json``).

    Raises:
        StoreError: ``run.json`` is missing or invalid, or a file is a symlink.
    """
    manifest: RunManifest = read_manifest(directory)
    for path in directory.rglob("*"):
        if path.is_symlink():
            msg = f"{path} is a symlink; exports hold regular files only"
            raise StoreError(msg)
    _write_marker(directory, manifest.run_id)

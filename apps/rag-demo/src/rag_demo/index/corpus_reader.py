"""Corpus reader: ``manifest.json`` and ``<tenant>.chunks.jsonl`` files, schema-checked per line.

The schema is the shipped copy ``chunk.schema.json`` (a test keeps it byte-equal to
``schemas/chunk.schema.json``); rag-demo never imports ``pruefstand``.
"""

import json
import uuid
from collections.abc import Iterator
from importlib import resources
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from rag_demo.errors import CorpusError

NAMESPACE = uuid.UUID("6f1a8f64-3c1e-4b0e-9d52-5f0b7b1c2a10")
SUFFIX = ".chunks.jsonl"


def point_id(chunk_id: str) -> str:
    """Return the stable Qdrant point id (UUID5) of a chunk id."""
    return str(uuid.uuid5(NAMESPACE, chunk_id))


def index_text(row: dict[str, Any]) -> str:
    """Text that is embedded and tokenised: the citation key first, so "§ 622 BGB" is findable."""
    key = row.get("citation_key")
    return f"{key}\n{row['text']}" if key else str(row["text"])


def read_manifest(corpus_dir: Path) -> dict[str, Any]:
    """Read ``manifest.json`` of a corpus directory.

    Raises:
        CorpusError: Missing, unreadable, not JSON, or without ``corpus_version`` / ``tenants``.
    """
    try:
        manifest = json.loads((corpus_dir / "manifest.json").read_text(encoding="utf-8"))
        if not {"corpus_version", "tenants"} <= manifest.keys():
            raise KeyError("corpus_version")  # noqa: EM101, TRY301
    except (OSError, json.JSONDecodeError, KeyError, AttributeError) as err:
        msg = f"cannot read corpus manifest in {corpus_dir}: {type(err).__name__}"
        raise CorpusError(msg) from None
    result: dict[str, Any] = manifest
    return result


def _validator() -> Draft202012Validator:
    text = (resources.files("rag_demo.index") / "chunk.schema.json").read_text(encoding="utf-8")
    return Draft202012Validator(json.loads(text))


def _check(path: Path, number: int, line: str, validator: Draft202012Validator) -> dict[str, Any]:
    try:
        row: dict[str, Any] = json.loads(line)
    except json.JSONDecodeError as err:
        msg = f"{path.name}:{number}: invalid JSON ({err.msg})"
        raise CorpusError(msg) from None
    errors = sorted(e.message for e in validator.iter_errors(row))
    if errors:
        msg = f"{path.name}:{number}: {errors[0]}"
        raise CorpusError(msg)
    if row["tenant"] != path.name.removesuffix(SUFFIX):
        msg = f"{path.name}:{number}: tenant {row['tenant']!r} does not match the file name"
        raise CorpusError(msg)
    return row


def iter_chunks(corpus_dir: Path) -> Iterator[dict[str, Any]]:
    """Stream every chunk row (file-name order, then line order), validating each line.

    Args:
        corpus_dir: ``corpus/<version>/``.

    Yields:
        One validated row per line.

    Raises:
        CorpusError: No chunk file, invalid JSON, a schema violation, or a row whose tenant is not
            the file's tenant; the message starts with ``<file>:<line>``.
    """
    files = sorted(corpus_dir.glob(f"*{SUFFIX}"))
    if not files:
        msg = f"no *{SUFFIX} files in {corpus_dir}"
        raise CorpusError(msg)
    validator = _validator()
    for path in files:
        with path.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if line.strip():
                    yield _check(path, number, line, validator)


def read_corpus(corpus_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read the manifest and all rows of ``corpus_dir`` (see ``iter_chunks``).

    Returns:
        ``(manifest, rows)``.

    Raises:
        CorpusError: Any problem of ``read_manifest`` or ``iter_chunks``.
    """
    return read_manifest(corpus_dir), list(iter_chunks(corpus_dir))

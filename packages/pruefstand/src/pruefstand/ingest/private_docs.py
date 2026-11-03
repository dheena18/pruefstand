"""``PrivateDocsLoader``: the human-approved synthetic private documents (T2.6 S3).

A file is Markdown with a YAML front matter (``PrivateDocFront``) and the body text. The loader
only reads and validates; planting the token canary is ``attacks.plant_canaries`` and happens in
``pipeline/ingest.py`` (``ingest`` and ``attacks`` never import each other).
"""

import re
from collections.abc import Iterator
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from pruefstand.core.enums import Lang
from pruefstand.core.errors import DatasetError
from pruefstand.core.ids import DocId, TenantId
from pruefstand.core.models.corpus import Document

MAX_FILE_BYTES = 256 * 1024
_FRONT = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)


class PrivateDocFront(BaseModel):
    """Front matter of an approved private document."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    doc_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    tenant: str = Field(min_length=1)
    title: str = Field(min_length=1)
    semantic_fact: str = Field(min_length=1)
    semantic_value: str = Field(min_length=1)
    probe_question: str = Field(min_length=1)
    forbidden_answer: str = Field(min_length=1)


def render_private_doc(front: PrivateDocFront, body: str) -> str:
    """Serialise front matter and body into the file format the loader reads.

    Args:
        front: The validated front matter.
        body: Markdown text.

    Returns:
        The file text (UTF-8, LF).
    """
    head = yaml.safe_dump(front.model_dump(), allow_unicode=True, sort_keys=False, width=1000)
    return f"---\n{head}---\n{body.strip(chr(10))}\n"


def parse_private_doc(text: str, origin: str) -> tuple[PrivateDocFront, str]:
    """Split a file into validated front matter and body.

    Args:
        text: File content.
        origin: File name for messages.

    Returns:
        The front matter and the body.

    Raises:
        DatasetError: No front matter, invalid YAML, a missing or unknown key, or an empty body.
    """
    match = _FRONT.match(text)
    if match is None:
        msg = f"{origin}: no front matter (file must start with '---')"
        raise DatasetError(msg)
    try:
        data = yaml.safe_load(match.group(1))
        front = PrivateDocFront.model_validate(data)
    except yaml.YAMLError as exc:
        msg = f"{origin}: front matter is not valid YAML"
        raise DatasetError(msg) from exc
    except ValidationError as exc:
        fields = ", ".join(sorted({str(e["loc"][0]) if e["loc"] else "?" for e in exc.errors()}))
        msg = f"{origin}: invalid front matter ({fields})"
        raise DatasetError(msg) from exc
    body = match.group(2).strip("\n")
    if not body.strip():
        msg = f"{origin}: empty body"
        raise DatasetError(msg)
    return front, body + "\n"


class PrivateDocsLoader:
    """Reads approved private documents as ``Document(source="private", license="own")``.

    Args:
        nested: True (default): ``<root>/<tenant>/*.md`` and the folder name must equal the
            tenant of the front matter; folders starting with ``_`` (drafts) are skipped. False:
            ``<root>/*.md`` (the held-out ``docs/`` folder).
    """

    def __init__(self, *, nested: bool = True) -> None:
        self._nested = nested

    def load(self, raw_dir: Path) -> Iterator[Document]:
        """Yield the documents in file-name order.

        Args:
            raw_dir: The approved-documents folder.

        Yields:
            One document per file; ``metadata`` carries the four semantic-canary keys.

        Raises:
            DatasetError: ``raw_dir`` is not a directory, a file is too large, unreadable or
                invalid, or its tenant differs from its folder.
        """
        if not raw_dir.is_dir():
            msg = f"{raw_dir.name}: not a directory (approved private documents)"
            raise DatasetError(msg)
        for path in self._files(raw_dir):
            yield self._read(path, raw_dir)

    def _files(self, raw_dir: Path) -> list[Path]:
        if not self._nested:
            return sorted(p for p in raw_dir.glob("*.md") if p.is_file())
        folders = sorted(p for p in raw_dir.iterdir() if p.is_dir() and not p.name.startswith("_"))
        return [f for folder in folders for f in sorted(folder.glob("*.md")) if f.is_file()]

    def _read(self, path: Path, raw_dir: Path) -> Document:
        origin = str(path.relative_to(raw_dir))
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                msg = f"{origin}: larger than {MAX_FILE_BYTES} bytes"
                raise DatasetError(msg)
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            msg = f"{origin}: cannot be read ({type(exc).__name__})"
            raise DatasetError(msg) from exc
        front, body = parse_private_doc(text, origin)
        if self._nested and path.parent.name != front.tenant:
            msg = f"{origin}: tenant {front.tenant!r} differs from its folder {path.parent.name!r}"
            raise DatasetError(msg)
        return Document(
            doc_id=DocId(front.doc_id), tenant=TenantId(front.tenant), source="private",
            lang=Lang.DE, title=front.title, law_abbrev=None, version_date=None, text=body,
            license="own", url=None,
            metadata={
                "semantic_fact": front.semantic_fact,
                "semantic_value": front.semantic_value,
                "probe_question": front.probe_question,
                "forbidden_answer": front.forbidden_answer,
            },
        )  # fmt: skip

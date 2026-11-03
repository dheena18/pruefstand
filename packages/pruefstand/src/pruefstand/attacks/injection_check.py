"""Validation of an injection set against the chunks of a corpus (T4.6 S5)."""

import base64
import binascii
import re
from collections import Counter
from collections.abc import Iterable, Sequence

from pruefstand.core.errors import DatasetError
from pruefstand.core.models.corpus import Chunk
from pruefstand.core.models.testcase import TestCase

_SHARED = "shared_public"
_BLOB = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")
_WORD = re.compile(r"[^\W\d_]{4,}")
_BASE64_TAG = "placement:base64"
_SHOWN = 5


def _decoded(text: str) -> str:
    parts: list[str] = []
    for blob in _BLOB.findall(text):
        try:
            parts.append(base64.b64decode(blob, validate=True).decode("utf-8"))
        except (binascii.Error, UnicodeDecodeError):
            continue
    return "\n".join(parts)


def _holds(case: TestCase, text: str) -> bool:
    marker = case.injection_marker or ""
    return marker in (_decoded(text) if _BASE64_TAG in case.tags else text)


def check_injection_set(cases: Iterable[TestCase], chunks: Sequence[Chunk]) -> None:
    """Check that the attack chunks and the injection cases belong together.

    Args:
        cases: The injection cases (``category=injection``).
        chunks: All chunks of the corpus.

    Raises:
        DatasetError: An attack chunk sits in ``shared_public``; a marker is not unique or does
            not appear in exactly one attack chunk of its tenant (for ``BASE64`` documents: in
            the decoded payload); or a content word (4+ letters) of the question does not occur
            in the document (retrievability proxy).
    """
    attack = [c for c in chunks if c.is_attack]
    if any(c.tenant == _SHARED for c in attack):
        msg = f"attack chunk(s) in {_SHARED}: attack documents belong to customer tenants only"
        raise DatasetError(msg)
    cases = list(cases)
    dup = [m for m, n in Counter(c.injection_marker for c in cases).items() if n > 1]
    if dup:
        msg = f"injection markers are not unique: {', '.join(sorted(map(str, dup))[:_SHOWN])}"
        raise DatasetError(msg)
    by_doc: dict[str, list[Chunk]] = {}
    for chunk in attack:
        by_doc.setdefault(chunk.doc_id, []).append(chunk)
    problems: list[str] = []
    for case in cases:
        held = [c for c in attack if c.tenant == case.tenant and _holds(case, c.text)]
        if len(held) != 1:
            problems.append(
                f"{case.id}: marker in {len(held)} attack chunks of {case.tenant}, need exactly one"
            )
            continue
        doc_text = "\n".join(c.text for c in by_doc.get(held[0].doc_id, [])).casefold()
        missing = [w for w in _WORD.findall(case.question.casefold()) if w not in doc_text]
        if held[0].doc_id != case.cluster_id or missing:
            problems.append(
                f"{case.id}: question words not in its attack document: {missing[:_SHOWN]}"
            )
    if problems:
        msg = f"{len(problems)} injection case(s) invalid: " + "; ".join(problems[:_SHOWN])
        raise DatasetError(msg)

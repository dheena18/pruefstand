"""Parsing of untrusted Target API v1 response bodies (used by ``http.py``).

Everything here is pure and synchronous: ``http.py`` runs it in a worker thread inside the
call's total deadline. Parsing is bounded before pydantic sees the data (list sizes, types of
the cheap fields), unknown keys are dropped and null optionals treated as absent so ordinary
third-party targets work, while type errors in known fields stay strict. Error messages never
contain the raw input: only a redacted excerpt of at most 200 characters.
"""

import json
import math
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, quote_plus

from pydantic import BaseModel, ValidationError

from pruefstand.core.errors import TargetError
from pruefstand.core.models.target import (
    RetrievedChunk,
    RetrieveResponse,
    TargetInfo,
    TargetResponse,
)

MAX_CITATIONS = 1000
MAX_CHUNKS = 10_000
EXCERPT_CHARS = 200
REDACTED = "[REDACTED]"

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]+")
_BEARER = re.compile(r"(?i)(bearer\s+)\S+")
_RESPONSE_KEYS = ("answer", "citations", "chunks", "refused", "model", "usage")
_CHUNK_KEYS = ("chunk_id", "doc_id", "tenant_id", "text", "score", "rank", "used_in_prompt")
_USAGE_KEYS = ("prompt_tokens", "completion_tokens")
_INFO_KEYS = (
    "app_version",
    "git_sha",
    "image_digest",
    "config_hash",
    "corpus_version",
    "models",
    "serving",
)

Parser = Callable[[bytes, str, tuple[str, ...]], Any]


def secret_forms(secret: str) -> tuple[str, ...]:
    """Return the plain, JSON-escaped (once and twice) and URL-encoded forms, longest first."""
    if not secret:
        return ()
    forms = {
        secret,
        json.dumps(secret)[1:-1],
        json.dumps(json.dumps(secret))[1:-1],  # echoed inside a JSON string inside JSON
        quote(secret),  # default safe="/"
        quote(secret, safe=""),
        quote_plus(secret),
    }
    return tuple(sorted(forms, key=len, reverse=True))


def excerpt(data: bytes, secrets: tuple[str, ...]) -> str:
    """Return a short, single-line, redacted excerpt of an untrusted body."""
    text = data[: EXCERPT_CHARS * 8].decode("utf-8", errors="replace")
    for form in secrets:
        text = text.replace(form, REDACTED)
    text = _BEARER.sub(rf"\1{REDACTED}", text)
    return _CONTROL.sub(" ", text).strip()[:EXCERPT_CHARS]


def _reject_constant(name: str) -> object:
    msg = f"non-finite number {name} is not valid JSON"
    raise ValueError(msg)


def load_json(data: bytes, what: str, secrets: tuple[str, ...]) -> object:
    """Parse ``data`` as JSON (BOM accepted, duplicate keys: last wins, no NaN/Infinity).

    Raises:
        TargetError: Not valid JSON, or not representable as UTF-8 (permanent). The raw parser
            exception is not chained: it holds the full input.
    """
    failure = ""
    body: object = None
    try:
        body = json.loads(data, parse_constant=_reject_constant)
        json.dumps(body, ensure_ascii=False).encode("utf-8")  # rejects lone surrogates
    except (ValueError, RecursionError) as exc:
        failure = type(exc).__name__
    if failure:
        msg = f"{what}: invalid JSON ({failure}): {excerpt(data, secrets)}"
        raise TargetError(msg, transient=False)
    return body


def _validate[M: BaseModel](model: type[M], body: object, what: str) -> M:
    problems = ""
    try:
        return model.model_validate(body)
    except ValidationError as exc:
        found = exc.errors(include_input=False, include_url=False, include_context=False)
        shown = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in found[:3])
        problems = f"{exc.error_count()} error(s): {shown}"
    msg = f"{what}: response does not match Target API v1 ({problems})"
    raise TargetError(msg[:400], transient=False)


def _pick(raw: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: raw[key] for key in keys if raw.get(key) is not None}


def _chunks(raw: object, what: str) -> object:
    if not isinstance(raw, list):
        return raw
    if len(raw) > MAX_CHUNKS:
        msg = f"{what}: too many chunks ({len(raw)} > {MAX_CHUNKS})"
        raise TargetError(msg, transient=False)
    return [_pick(c, _CHUNK_KEYS) if isinstance(c, dict) else c for c in raw]


def _citations(raw: object, what: str) -> list[str]:
    """Validate citations: strings, plus integer ids (not bool) that are stringified.

    Many third-party RAG targets cite by number (``[1, 2]``); ``"1"`` is the faithful string
    form. Every other non-string item (bool, float, null, list, object) is a permanent error.
    """
    if not isinstance(raw, list):
        msg = f"{what}: citations must be a list of strings or integers"
        raise TargetError(msg, transient=False)
    if len(raw) > MAX_CITATIONS:
        msg = f"{what}: too many citations ({len(raw)} > {MAX_CITATIONS})"
        raise TargetError(msg, transient=False)
    out: list[str] = []
    for item in raw:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, int) and not isinstance(item, bool):
            out.append(str(item))
        else:
            msg = f"{what}: citations must be a list of strings or integers"
            raise TargetError(msg, transient=False)
    return out


def _check_finite(chunks: tuple[RetrievedChunk, ...] | None, what: str) -> None:
    if chunks is not None and not all(math.isfinite(chunk.score) for chunk in chunks):
        msg = f"{what}: chunk score is not a finite number"
        raise TargetError(msg, transient=False)


def parse_query(data: bytes, what: str, secrets: tuple[str, ...]) -> TargetResponse:
    """Parse a ``/v1/query`` body: unknown keys dropped, null optionals absent.

    A ``usage`` object that lacks either token count is dropped as absent, so ``usage is None``
    can also mean "partial usage reported" (a future token-cost metric must not read it as
    "none reported"). Integer citation ids become strings.
    """
    body = load_json(data, what, secrets)
    if isinstance(body, dict):
        body = _pick(body, _RESPONSE_KEYS)
        if "citations" in body:
            body["citations"] = _citations(body["citations"], what)
        if "chunks" in body:
            body["chunks"] = _chunks(body["chunks"], what)
        usage = body.get("usage")
        if isinstance(usage, dict):
            picked = _pick(usage, _USAGE_KEYS)
            if len(picked) == len(_USAGE_KEYS):
                body["usage"] = picked
            else:
                del body["usage"]  # no token counts: treat usage as absent
    response = _validate(TargetResponse, body, what)
    _check_finite(response.chunks, what)
    return response


def parse_retrieve(data: bytes, what: str, secrets: tuple[str, ...]) -> RetrieveResponse:
    """Parse a ``/v1/retrieve`` body; a retrieve endpoint must not return an ``answer``."""
    body = load_json(data, what, secrets)
    if isinstance(body, dict):
        if "answer" in body:
            msg = f"{what}: response contains an 'answer'; a retrieve endpoint must not generate"
            raise TargetError(msg, transient=False)
        body = _pick(body, ("chunks",))
        if "chunks" in body:
            body["chunks"] = _chunks(body["chunks"], what)
    response = _validate(RetrieveResponse, body, what)
    _check_finite(response.chunks, what)
    return response


def parse_info(data: bytes, what: str, secrets: tuple[str, ...]) -> TargetInfo:
    """Parse a ``/v1/info`` body: unknown keys dropped, ``serving: null`` means ``{}``."""
    body = load_json(data, what, secrets)
    if isinstance(body, dict):
        body = _pick(body, _INFO_KEYS)
        body.setdefault("image_digest", None)
    return _validate(TargetInfo, body, what)

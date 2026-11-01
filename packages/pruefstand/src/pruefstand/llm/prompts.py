"""Prompt registry: ``<prompt_id>_v<N>.txt`` files with ``### system`` / ``### user`` sections."""

import hashlib
import re
from collections.abc import Sequence
from pathlib import Path

from pruefstand.core.errors import PromptError
from pruefstand.core.models.llm import PromptTemplate

DEFAULT_ROOT = Path(__file__).resolve().parent / "prompts"
_SECTION = re.compile(r"^### (system|user)[ \t]*$", re.MULTILINE)
_VERSION = re.compile(r"^v[0-9]+$")
_PROMPT_ID = re.compile(r"^[a-z0-9_.]+$")


class PromptRegistry:
    """Loads versioned prompt files from one or more roots (first match wins).

    Args:
        roots: Directories to search; default is the package data ``pruefstand/llm/prompts/``.
    """

    def __init__(self, roots: Sequence[Path] | None = None) -> None:
        self._roots = tuple(roots) if roots else (DEFAULT_ROOT,)
        self._cache: dict[tuple[str, str], PromptTemplate] = {}

    def get(self, prompt_id: str, version: str) -> PromptTemplate:
        """Return the template ``<prompt_id>_<version>.txt``.

        Args:
            prompt_id: Prompt name, for example ``echo``.
            version: ``v<N>``.

        Returns:
            The parsed template with the SHA-256 of the file bytes.

        Raises:
            PromptError: Bad version, file not found, or malformed sections.
        """
        key = (prompt_id, version)
        if key not in self._cache:
            self._cache[key] = self._load(prompt_id, version)
        return self._cache[key]

    def _load(self, prompt_id: str, version: str) -> PromptTemplate:
        if not _PROMPT_ID.fullmatch(prompt_id):
            msg = f"prompt_id '{prompt_id}' must match [a-z0-9_.]+"
            raise PromptError(msg)
        if not _VERSION.match(version):
            msg = f"prompt version '{version}' is not of the form v<N>"
            raise PromptError(msg)
        name = f"{prompt_id}_{version}.txt"
        for root in self._roots:
            path = root / name
            if path.is_file():
                return _parse(prompt_id, version, path.read_bytes())
        msg = f"prompt file {name} not found in {[str(r) for r in self._roots]}"
        raise PromptError(msg)


def _parse(prompt_id: str, version: str, raw: bytes) -> PromptTemplate:
    text = raw.decode("utf-8")
    parts = _SECTION.split(text)
    if parts[0].strip():
        msg = f"prompt {prompt_id}_{version}: text before the first ### section"
        raise PromptError(msg)
    sections: dict[str, str] = {}
    for name, body in zip(parts[1::2], parts[2::2], strict=True):
        if name in sections:
            msg = f"prompt {prompt_id}_{version}: duplicate ### {name} section"
            raise PromptError(msg)
        sections[name] = body.strip("\n")
    if "user" not in sections:
        msg = f"prompt {prompt_id}_{version}: no ### user section"
        raise PromptError(msg)
    return PromptTemplate(
        prompt_id=prompt_id,
        version=version,
        sha256=hashlib.sha256(raw).hexdigest(),
        system=sections.get("system", ""),
        user=sections["user"],
    )

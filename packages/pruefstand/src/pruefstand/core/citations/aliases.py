"""Law-name map: ``core/data/law_aliases.yaml`` loaded once, plus the regex built from it.

The YAML file is the only law-name table in the repository (T1.5a). Lookups fold case and
whitespace, so ``"german  civil code"`` resolves to ``"BGB"``.
"""

import re
from functools import cache
from importlib.resources import files
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

from pruefstand.core.errors import ConfigError

_CONNECTOR = r"(?:(?:des|der|dem|von|vom|of\s+the|of)\s+)?"


class LawAliases(BaseModel):
    """The parsed alias file: canonical abbreviation to alias list, per scope."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1]
    national: dict[str, tuple[str, ...]]
    eu: dict[str, tuple[str, ...]]

    def all_laws(self) -> dict[str, tuple[str, ...]]:
        """Return national and EU laws in one mapping (abbreviation to aliases)."""
        return {**self.national, **self.eu}


def _fold(name: str) -> str:
    return " ".join(name.split()).casefold()


@cache
def law_aliases() -> LawAliases:
    """Load and validate the packaged alias file (once per process).

    Returns:
        The parsed table.

    Raises:
        ConfigError: if the file is malformed or one alias names two different laws.
    """
    raw = files("pruefstand.core.data").joinpath("law_aliases.yaml").read_text(encoding="utf-8")
    try:
        table = LawAliases.model_validate(yaml.safe_load(raw))
    except ValueError as exc:
        msg = f"law_aliases.yaml is invalid: {exc}"
        raise ConfigError(msg) from exc
    _lookup_of(table)
    return table


def _lookup_of(table: LawAliases) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for abbreviation, aliases in table.all_laws().items():
        for name in (abbreviation, *aliases):
            if lookup.setdefault(_fold(name), abbreviation) != abbreviation:
                msg = f"law alias {name!r} names two laws"
                raise ConfigError(msg)
    return lookup


@cache
def _lookup() -> dict[str, str]:
    return _lookup_of(law_aliases())


@cache
def _law_regex() -> re.Pattern[str]:
    names = sorted(_lookup_of(law_aliases()), key=len, reverse=True)
    alternatives = "|".join(re.escape(n).replace(r"\ ", r"\s+") for n in names)
    return re.compile(rf"\s*{_CONNECTOR}(?P<law>{alternatives})(?!\w)", re.IGNORECASE)


def resolve_law(name: str) -> str | None:
    """Map a law name or abbreviation to its canonical abbreviation.

    Args:
        name: e.g. ``"GDPR"``, ``"Bürgerlichen Gesetzbuchs"``.

    Returns:
        The canonical abbreviation (``"DSGVO"``, ``"BGB"``) or ``None`` when unknown.

    Examples:
        >>> resolve_law("GDPR")
        'DSGVO'
        >>> resolve_law("nonsense") is None
        True
    """
    return _lookup().get(_fold(name))


def is_national(abbreviation: str) -> bool:
    """Return True when the canonical abbreviation is a German national law."""
    return abbreviation in law_aliases().national


def match_law(text: str, pos: int) -> tuple[str, int] | None:
    """Match a law name at ``pos`` (leading whitespace and "des"/"of the" allowed).

    Args:
        text: The text being scanned.
        pos: Where the law name is expected.

    Returns:
        ``(canonical abbreviation, end position)`` or ``None``.
    """
    m = _law_regex().match(text, pos)
    if m is None:
        return None
    law = resolve_law(m.group("law"))
    return (law, m.end()) if law is not None else None

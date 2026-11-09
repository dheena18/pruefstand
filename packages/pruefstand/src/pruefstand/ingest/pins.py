"""Pinned source versions for the corpus manifest (T2.5): read from ``data/sources.yaml`` (T2.1)."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from pruefstand.core.config_loader import load_model
from pruefstand.core.errors import ConfigError

# Loader source -> id of the pin in data/sources.yaml (the OLDP loader's source is a label).
_ALIASES = {"oldp:decisions": "oldp_decisions"}
SYNTHETIC_PIN = "synthetic"


class _SourcesFile(BaseModel):
    """``data/sources.yaml``: only the ``sources`` list matters here (T2.1 checks the entries)."""

    model_config = ConfigDict(extra="ignore")

    sources: list[object]


def load_pins(path: Path) -> dict[str, str]:
    """Return ``{source id: pinned version}`` for every entry of ``data/sources.yaml``.

    The pin is ``pinned`` (the download date of a GII or EUR-Lex file) or ``revision`` (the commit
    of a Hugging Face dataset). The file is read with the hardened config loader (regular file, no
    symlink, size cap, ``safe_load``, no aliases or duplicate keys, bounded nesting).

    Args:
        path: ``data/sources.yaml``.

    Returns:
        E.g. ``{"gii:kschg": "2026-10-31", "oldp_decisions": "408eb91..."}``.

    Raises:
        ConfigError: The file is missing, too large, not YAML or not shaped like the pin list.
    """
    entries = load_model(path, _SourcesFile).sources
    pins: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            continue
        pin = entry.get("pinned") or entry.get("revision")
        if pin:
            pins[entry["id"]] = str(pin)
    return pins


def pin_for(source: str, pins: dict[str, str], pins_file: Path) -> str:
    """Return the pinned version of a loader ``source``.

    Args:
        source: ``Document.source`` (``"gii:kschg"``, ``"oldp:decisions"``).
        pins: Result of :func:`load_pins`.
        pins_file: The file the pins came from (named in the error).

    Raises:
        ConfigError: The source has no pin; an unpinned source would make the corpus version
            claim a provenance it cannot show.
    """
    pin = pins.get(_ALIASES.get(source, source))
    if pin is None:
        msg = f"source {source!r} has no pin in {pins_file}"
        raise ConfigError(msg)
    return pin

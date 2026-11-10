"""A40 endpoint map and per-model options, read from ``infra/gpu/*.yaml`` at use time (Y3.2).

Nothing here pins a model: ids, digests and options come from the catalogue, so T3.1b can change
the pins in ``models.yaml`` without a code change. ``build_backend`` reads only the endpoint file;
the catalogue is read when a request is made (DEV12-11).
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from pruefstand.core.errors import ConfigError
from pruefstand.core.settings import PruefstandSettings

DEFAULT_URL_ENV = "OLLAMA_GPU0_URL"  # the generator lane, for ids the endpoint table does not list
OPTION_KEYS = ("num_ctx", "num_predict", "temperature", "seed", "top_p")
_MAX_BYTES = 1_000_000
_SERVER_GPUS = {"gpu0": 1, "gpu1": 1, "all": 2, "vm": 0}


@dataclass(frozen=True)
class CatalogueEntry:
    """One ``ollama`` entry of ``models.yaml`` (the fields the LLM layer needs)."""

    id: str
    tag: str
    server: str
    digest: str | None
    options: Mapping[str, float]
    quantization: str | None = None
    tokenizer_source: str | None = None
    tokenizer_sha256: str | None = None


def _load_yaml(path: Path, what: str) -> dict[str, object]:
    try:
        with path.open("rb") as handle:
            raw = handle.read(_MAX_BYTES + 1)
    except OSError as err:
        msg = f"{what} file {path} cannot be read ({type(err).__name__})"
        raise ConfigError(msg) from err
    if len(raw) > _MAX_BYTES:
        msg = f"{what} file {path} is larger than {_MAX_BYTES} bytes"
        raise ConfigError(msg)
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as err:
        msg = f"{what} file {path} is not valid YAML"
        raise ConfigError(msg) from err
    if not isinstance(data, dict):
        msg = f"{what} file {path} must hold a mapping"
        raise ConfigError(msg)
    return data


def endpoint_env(model_id: str, endpoints_file: Path) -> str:
    """Return the name of the env var that holds the base URL serving ``model_id``.

    Args:
        model_id: ``ollama/<tag>``.
        endpoints_file: ``infra/gpu/endpoints.yaml`` (or a test copy).

    Returns:
        ``base_url_env`` of the endpoint whose ``model_id`` matches; ``OLLAMA_GPU0_URL`` when the
        table does not list the id (swap candidates run on the generator lane).

    Raises:
        ConfigError: The file is unreadable or has no ``endpoints`` mapping.
    """
    table = _load_yaml(endpoints_file, "endpoints").get("endpoints")
    if not isinstance(table, dict):
        msg = f"endpoints file {endpoints_file}: missing 'endpoints' mapping"
        raise ConfigError(msg)
    for entry in table.values():
        if isinstance(entry, dict) and entry.get("model_id") == model_id:
            return str(entry["base_url_env"])
    return DEFAULT_URL_ENV


def ollama_base_url(model_id: str, *, env: Mapping[str, str] | None = None) -> str:
    """Return the base URL (no ``/v1``) of the Ollama server for ``model_id``.

    Raises:
        ConfigError: The endpoints file is bad, or the env var it names is unset (named in the
            message).
    """
    settings = PruefstandSettings()
    name = endpoint_env(model_id, settings.gpu_endpoints_file)
    value = (os.environ if env is None else env).get(name, "")
    if not value:
        msg = (
            f"environment variable {name} is not set (base URL of the Ollama server for {model_id})"
        )
        raise ConfigError(msg)
    return value.rstrip("/")


def _tokenizer_pin(raw: object) -> tuple[str | None, str | None]:
    if not isinstance(raw, dict):
        return None, None
    source, sha256 = raw.get("source"), raw.get("sha256")
    return (str(source), str(sha256)) if source and sha256 else (None, None)


@lru_cache(maxsize=8)
def _entries(path: str, mtime_ns: int) -> dict[str, CatalogueEntry]:
    del mtime_ns  # part of the cache key only
    data = _load_yaml(Path(path), "catalogue").get("models")
    if not isinstance(data, list):
        msg = f"catalogue file {path}: missing 'models' list"
        raise ConfigError(msg)
    out: dict[str, CatalogueEntry] = {}
    for raw in data:
        if not isinstance(raw, dict) or raw.get("engine") != "ollama":
            continue
        mid = str(raw.get("id", ""))
        if not mid.startswith("ollama/"):
            msg = f"catalogue {path}: ollama entry '{mid}' must have an id starting with 'ollama/'"
            raise ConfigError(msg)
        opts = raw.get("options")
        if not isinstance(opts, dict) or not set(OPTION_KEYS) <= set(opts):
            msg = f"catalogue {path}: '{mid}' needs the options {', '.join(OPTION_KEYS)}"
            raise ConfigError(msg)
        digest = raw.get("digest")
        out[mid] = CatalogueEntry(
            mid,
            str(raw.get("tag", mid.removeprefix("ollama/"))),
            str(raw.get("server", "gpu0")),
            str(digest) if digest else None,
            {k: opts[k] for k in OPTION_KEYS},
            str(raw["quantization"]) if raw.get("quantization") else None,
            *_tokenizer_pin(raw.get("tokenizer")),
        )
    return out


def catalogue_entry(model_id: str, path: Path | None = None) -> CatalogueEntry:
    """Look ``model_id`` up in the catalogue (``PRUEFSTAND_GPU_CATALOGUE``) at request time.

    Raises:
        ConfigError: File unreadable or invalid, or ``model_id`` is not an entry (named).
    """
    file = path or PruefstandSettings().gpu_catalogue_file
    try:
        mtime = file.stat().st_mtime_ns
    except OSError as err:
        msg = f"catalogue file {file} cannot be read ({type(err).__name__})"
        raise ConfigError(msg) from err
    entries = _entries(str(file), mtime)
    if model_id not in entries:
        msg = f"model '{model_id}' is not in the GPU catalogue {file}"
        raise ConfigError(msg)
    return entries[model_id]


def catalogue_options(model_id: str, path: Path | None = None) -> Mapping[str, float]:
    """Return the five fixed options (``num_ctx`` ... ``top_p``) of ``model_id``."""
    return catalogue_entry(model_id, path).options


def server_gpus(server: str) -> int:
    """Return the GPUs a catalogue ``server`` value stands for (``gpu0``/``gpu1`` 1, ``all`` 2)."""
    return _SERVER_GPUS.get(server, 1)

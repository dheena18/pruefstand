"""``load_config``: YAML file -> validated, frozen ``PruefstandConfig``."""

from pathlib import Path

import yaml
from pydantic import ValidationError

from pruefstand.core.config import PruefstandConfig
from pruefstand.core.errors import ConfigError

MAX_CONFIG_BYTES = 1_000_000  # 1 MB: configs are small; a larger file is an error, not a workload


def _read(path: Path) -> str:
    try:
        size = path.stat().st_size
        if size > MAX_CONFIG_BYTES:
            msg = f"{path}: config file too large ({size} bytes, limit {MAX_CONFIG_BYTES})"
            raise ConfigError(msg)
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        msg = f"{path}: cannot read config: {exc}"
        raise ConfigError(msg) from exc


def _parse(path: Path, text: str) -> dict[str, object]:
    try:
        # Aliases are refused before loading: a tiny file of nested aliases can expand to gigabytes.
        if any(
            isinstance(event, yaml.AliasEvent) for event in yaml.parse(text, Loader=yaml.SafeLoader)
        ):
            msg = f"{path}: YAML aliases (*name) are not allowed in configs"
            raise ConfigError(msg)
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        msg = f"{path}: invalid YAML: {exc}"
        raise ConfigError(msg) from exc
    if not isinstance(data, dict):
        msg = f"{path}: the config must be a YAML mapping at the top level"
        raise ConfigError(msg)
    return data


def _format(path: Path, exc: ValidationError) -> str:
    lines = []
    for err in exc.errors(include_url=False, include_input=False):
        where = ".".join(str(part) for part in err["loc"]) or "<root>"
        lines.append(f"{path}: {where}: {err['msg']}")
    return "\n".join(lines)


def load_config(path: Path) -> PruefstandConfig:
    """Read, parse and validate a ``pruefstand.yaml``.

    The file is parsed with ``yaml.safe_load`` only; files over 1 MB and YAML aliases are refused.
    There is no environment interpolation: secrets are referenced by env-var *name*
    (``target.auth_env``). Every validation error is reported at once, qualified with its YAML
    path such as ``gate.metrics.faithfulness.max_drop``.

    Args:
        path: The YAML file.

    Returns:
        The validated, frozen configuration.

    Raises:
        ConfigError: unreadable or oversized file, invalid YAML, a non-mapping document, or any
            validation failure (family rules of ADR-0009, unknown metrics, ranges, ...).
    """
    data = _parse(path, _read(path))
    try:
        return PruefstandConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(_format(path, exc)) from exc
    except ConfigError as exc:
        msg = f"{path}: {exc}"
        raise ConfigError(msg) from exc

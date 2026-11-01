"""``load_config``: YAML file -> validated, frozen ``PruefstandConfig``."""

import os
import stat
from pathlib import Path

import yaml
from pydantic import ValidationError

from pruefstand.core.config import PruefstandConfig
from pruefstand.core.config.gate import _SECRET_KEY
from pruefstand.core.errors import ConfigError

MAX_CONFIG_BYTES = 1_000_000  # 1 MB: configs are small; a larger file is an error, not a workload
MAX_CONFIG_DEPTH = 32  # nesting of mappings/sequences; real configs stay below 8


def _read(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                msg = f"{path}: not a regular file"
                raise ConfigError(msg)
            raw = handle.read(MAX_CONFIG_BYTES + 1)
        if len(raw) > MAX_CONFIG_BYTES:
            msg = f"{path}: config file too large (limit {MAX_CONFIG_BYTES} bytes)"
            raise ConfigError(msg)
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        msg = f"{path}: cannot read config: not valid UTF-8 (byte {exc.start})"
        raise ConfigError(msg) from exc
    except OSError as exc:
        msg = f"{path}: cannot read config (must be a regular file, not a symlink): {exc.strerror}"
        raise ConfigError(msg) from exc


def _mark_line(event: yaml.Event) -> int:
    mark = event.start_mark
    return mark.line + 1 if mark is not None else 0


def _check_key(path: Path, event: yaml.Event, frame: tuple[set[str], list[int]]) -> None:
    """Count a node of a mapping; a scalar in key position must not repeat."""
    keys, count = frame
    count[0] += 1
    if count[0] % 2 == 0 or not isinstance(event, yaml.ScalarEvent):
        return
    if event.value in keys:
        msg = f"{path}: line {_mark_line(event)}: duplicate key in mapping"
        raise ConfigError(msg)
    keys.add(event.value)


def _scan(path: Path, text: str) -> None:
    """Refuse aliases, duplicate keys and deep nesting before anything is built.

    Event based, so it never recurses: a hostile file is rejected after at most
    ``MAX_CONFIG_DEPTH + 1`` levels.
    """
    frames: list[tuple[set[str], list[int]] | None] = []  # per open node: mapping state or None
    for event in yaml.parse(text, Loader=yaml.SafeLoader):
        if isinstance(event, yaml.AliasEvent):
            msg = (
                f"{path}: line {_mark_line(event)}: YAML aliases (*name) are not allowed in configs"
            )
            raise ConfigError(msg)
        if isinstance(event, yaml.CollectionEndEvent):
            frames.pop()
            continue
        if frames and (frame := frames[-1]) is not None:
            _check_key(path, event, frame)
        if isinstance(event, yaml.MappingStartEvent):
            frames.append((set(), [0]))
        elif isinstance(event, yaml.SequenceStartEvent):
            frames.append(None)
        if len(frames) > MAX_CONFIG_DEPTH:
            msg = f"{path}: line {_mark_line(event)}: nested deeper than {MAX_CONFIG_DEPTH} levels"
            raise ConfigError(msg)


def _yaml_message(path: Path, exc: yaml.YAMLError) -> str:
    """Position and reason only: never the source snippet (it may hold a secret)."""
    mark = getattr(exc, "problem_mark", None)
    problem = getattr(exc, "problem", None) or "syntax error"
    where = f" line {mark.line + 1}, column {mark.column + 1}" if mark is not None else ""
    return f"{path}:{where}: invalid YAML: {problem}"


def _parse(path: Path, text: str) -> dict[str, object]:
    try:
        _scan(path, text)
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(_yaml_message(path, exc)) from exc
    except RecursionError as exc:
        msg = f"{path}: nested deeper than the parser allows"
        raise ConfigError(msg) from exc
    if not isinstance(data, dict):
        msg = f"{path}: the config must be a YAML mapping at the top level"
        raise ConfigError(msg)
    return data


def _format(path: Path, exc: ValidationError) -> str:
    lines = []
    for err in exc.errors(include_url=False, include_input=False):
        loc = [str(part) for part in err["loc"]]
        if err["type"] == "extra_forbidden" and loc and _SECRET_KEY.search(loc[-1]):
            loc[-1] = "<redacted key>"  # a stray `token: sk-...` must not leak into logs
        lines.append(f"{path}: {'.'.join(loc) or '<root>'}: {err['msg']}")
    return "\n".join(lines)


def load_config(path: Path) -> PruefstandConfig:
    """Read, parse and validate a ``pruefstand.yaml``.

    The file must be a regular file (no symlink) of at most 1 MB, parsed with ``yaml.safe_load``
    only. YAML aliases, duplicate keys and nesting deeper than 32 levels are refused. There is no
    environment interpolation: secrets are referenced by env-var *name* (``target.auth_env``).
    Every validation error is reported at once, qualified with its YAML path such as
    ``gate.metrics.faithfulness.max_drop``; messages never quote file content or input values.

    Args:
        path: The YAML file.

    Returns:
        The validated, frozen configuration.

    Raises:
        ConfigError: unreadable, non-regular or oversized file, invalid YAML, a non-mapping
            document, or any validation failure (family rules of ADR-0009, unknown metrics, ...).
    """
    data = _parse(path, _read(path))
    try:
        return PruefstandConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(_format(path, exc)) from exc
    except ConfigError as exc:
        msg = f"{path}: {exc}"
        raise ConfigError(msg) from exc

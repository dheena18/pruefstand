"""Structured logging with secret redaction (CLAUDE.md §5; A8-48).

Two processors run on every event, for structlog and stdlib records alike: one redacts the
value of keys that look like credentials, the other redacts token-shaped substrings inside any
string value, including formatted exception text.
"""

import logging
import re
import sys
from collections.abc import Mapping

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

REDACTED = "[REDACTED]"
_KEY_PATTERN = re.compile(r"token|key|secret|password|authorization", re.IGNORECASE)
_VALUE_PATTERN = re.compile(r"(?:sk-|hf_|gh[pousr]_)[A-Za-z0-9_]{8,}")
_HANDLER_MARK = "_pruefstand_handler"
_state = {"configured": False}


def _redact_value(value: object) -> object:
    if isinstance(value, str):
        return _VALUE_PATTERN.sub(REDACTED, value)
    if isinstance(value, Mapping):
        return {k: _redact_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_redact_value(v) for v in value]
    if value is None or isinstance(value, bool | int | float):
        return value
    text = repr(value)  # exceptions and other objects: JSON falls back to repr
    redacted = _VALUE_PATTERN.sub(REDACTED, text)
    return value if redacted == text else redacted


def _redact_mapping(mapping: Mapping[str, object]) -> dict[str, object]:
    return {
        k: REDACTED if _KEY_PATTERN.search(k) else _redact_nested(v) for k, v in mapping.items()
    }


def _redact_nested(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            k: REDACTED if isinstance(k, str) and _KEY_PATTERN.search(k) else _redact_nested(v)
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [_redact_nested(v) for v in value]
    return value


def _redact_keys(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    """Structlog processor: replace the value of every credential-looking key."""
    return _redact_mapping(event_dict)


def _redact_values(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    """Structlog processor: mask token-shaped substrings in every string value."""
    return {k: _redact_value(v) for k, v in event_dict.items()}


def _shared_processors() -> list[Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _redact_keys,
        _redact_values,
    ]


def configure_logging(*, json: bool = False, level: str = "INFO") -> None:
    """Configure structlog and the stdlib root logger; safe to call repeatedly.

    Records go to stderr. Stdlib records of third-party libraries pass through the same
    redaction.

    Args:
        json: One JSON object per line (CI) instead of coloured console output.
        level: Level name such as ``"INFO"`` or ``"WARNING"``.

    Raises:
        ValueError: ``level`` is not a standard logging level name.
    """
    numeric = logging.getLevelNamesMapping().get(level.upper())
    if numeric is None:
        msg = f"unknown log level {level!r}"
        raise ValueError(msg)
    shared = _shared_processors()
    renderer: Processor = (
        structlog.processors.JSONRenderer(sort_keys=True, ensure_ascii=False)
        if json
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    handler = logging.StreamHandler(sys.stderr)
    setattr(handler, _HANDLER_MARK, True)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
            foreign_pre_chain=shared,
        )
    )
    root = logging.getLogger()
    for old in [h for h in root.handlers if getattr(h, _HANDLER_MARK, False)]:
        root.removeHandler(old)
    root.addHandler(handler)
    root.setLevel(numeric)
    _state["configured"] = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a logger; configures logging with defaults on first use so redaction is always on.

    Args:
        name: Usually ``__name__``.

    Returns:
        A bound logger. Event names are ``snake_case`` verb phrases; data goes in keyword fields.
    """
    if not _state["configured"]:
        configure_logging()
    logger: structlog.stdlib.BoundLogger = structlog.stdlib.get_logger(name)
    return logger


__all__ = ["REDACTED", "configure_logging", "get_logger"]

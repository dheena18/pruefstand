"""Kill switch of the public demo: ``DEMO_ENABLED=false`` or a flag file, checked per request."""

import os
from collections.abc import Mapping
from pathlib import Path

DEFAULT_FLAG = Path("/run/demo/disabled")
_OFF = frozenset({"false", "0", "no", "off"})


def demo_disabled(env: Mapping[str, str] | None = None, flag: Path = DEFAULT_FLAG) -> bool:
    """True when the demo is switched off.

    Args:
        env: The environment (default ``os.environ``).
        flag: The flag file; its existence switches the demo off, whatever it contains.

    >>> demo_disabled({"DEMO_ENABLED": "false"}, Path("/nonexistent/x"))
    True
    >>> demo_disabled({}, Path("/nonexistent/x"))
    False
    """
    values = os.environ if env is None else env
    if values.get("DEMO_ENABLED", "true").strip().lower() in _OFF:
        return True
    return flag.exists()

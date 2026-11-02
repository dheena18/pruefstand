"""``load_canary_registry``: the registry that ``export-public`` and ``export-dashboard`` use.

It merges the public slice registry ``corpus/*/canaries.public.json``, the T2.6 registries
``datasets/canaries/*/canaries.json`` and, when ``PRUEFSTAND_HELDOUT_DIR`` is set,
``$PRUEFSTAND_HELDOUT_DIR/canaries_heldout.json``. It runs only in the executor's trusted steps;
the held-out registry is never mounted into a candidate container (round 9 X2.5).
"""

import os
from collections.abc import Mapping
from pathlib import Path

from pydantic import ValidationError

from pruefstand.core.errors import StoreError
from pruefstand.core.models.attacks import Canary, CanaryRegistry
from pruefstand.store._run_files import read_bounded
from pruefstand.store._safe_error import safe_error

MAX_REGISTRY_BYTES = 8 * 1024 * 1024
HELDOUT_FILE = "canaries_heldout.json"
_PUBLIC = ("corpus/*/canaries.public.json", "datasets/canaries/*/canaries.json")


def _read(path: Path) -> tuple[Canary, ...]:
    raw = read_bounded(path, MAX_REGISTRY_BYTES)
    try:
        return CanaryRegistry.model_validate_json(raw).canaries
    except ValidationError as exc:
        msg = f"invalid canary registry {path.name}: {safe_error(exc)}"
        raise StoreError(msg) from exc


def load_canary_registry(
    *, root: Path | None = None, env: Mapping[str, str] | None = None
) -> CanaryRegistry:
    """Merge every canary registry that exists.

    Args:
        root: Repository root that holds ``corpus/`` and ``datasets/`` (default: the current
            directory).
        env: Environment; ``PRUEFSTAND_HELDOUT_DIR`` names the held-out directory. Default
            ``os.environ``.

    Returns:
        All canaries, public first, de-duplicated by token.

    Raises:
        StoreError: No registry file found (never export unsanitised), the held-out directory
            is named but has no ``canaries_heldout.json``, or a file is too large, a symlink or
            invalid. Messages never contain text from the files.
    """
    base = Path.cwd() if root is None else root
    values = os.environ if env is None else env
    files = sorted(path for pattern in _PUBLIC for path in base.glob(pattern))
    heldout_dir = values.get("PRUEFSTAND_HELDOUT_DIR")
    if heldout_dir:
        heldout = Path(heldout_dir) / HELDOUT_FILE
        if not heldout.is_file():
            msg = f"PRUEFSTAND_HELDOUT_DIR is set but has no {HELDOUT_FILE}: no held-out registry"
            raise StoreError(msg)
        files.append(heldout)
    if not files:
        msg = f"no canary registry found under {base}: refusing to export without one"
        raise StoreError(msg)
    seen: dict[str, Canary] = {}
    for path in files:
        for canary in _read(path):
            seen.setdefault(canary.token, canary)
    return CanaryRegistry(canaries=tuple(seen.values()))

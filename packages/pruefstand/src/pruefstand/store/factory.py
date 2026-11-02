"""``build_baseline_store``: the store a ``BaselineStoreConfig`` describes (T6.1)."""

import os
from collections.abc import Mapping
from pathlib import Path

from pruefstand.core.config import BaselineStoreConfig
from pruefstand.core.protocols import BaselineStore
from pruefstand.store.baselines_git import GitBranchBaselineStore
from pruefstand.store.baselines_local import LocalDirBaselineStore


def resolve_data_root(cfg: BaselineStoreConfig, env: Mapping[str, str] | None = None) -> Path:
    """Where the run files of a ``git_branch`` store live (R9 X2.7, R10 D209, ADR-0019).

    ``data_root`` if set, else ``$PRUEFSTAND_DATA_ROOT/baselines``, else
    ``$PRUEFSTAND_HOME/baselines`` (default ``~/pruefstand``) for local development and CI.

    Args:
        cfg: The store configuration.
        env: Environment; default ``os.environ``.

    Returns:
        The directory (it need not exist).
    """
    if cfg.data_root is not None:
        return cfg.data_root
    values = os.environ if env is None else env
    data_root = values.get("PRUEFSTAND_DATA_ROOT")
    if data_root:
        return Path(data_root) / "baselines"
    return Path(values.get("PRUEFSTAND_HOME") or "~/pruefstand").expanduser() / "baselines"


def build_baseline_store(cfg: BaselineStoreConfig) -> BaselineStore:
    """Build the store of ``cfg``; no git command and no file access happens here.

    Args:
        cfg: ``type="local_dir"`` needs ``path``; ``type="git_branch"`` needs ``repo``.

    Returns:
        A ``LocalDirBaselineStore`` or a ``GitBranchBaselineStore``.
    """
    if cfg.type == "local_dir":
        return LocalDirBaselineStore(Path(str(cfg.path)))
    sentinel = cfg.data_root is None and bool(os.environ.get("PRUEFSTAND_DATA_ROOT"))
    return GitBranchBaselineStore(
        str(cfg.repo),
        resolve_data_root(cfg),
        branch=cfg.branch,
        require_sentinel=sentinel,
    )

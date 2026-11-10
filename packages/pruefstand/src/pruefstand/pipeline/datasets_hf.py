"""``hf://<user>/<name>@<revision>``: fetch a published dataset, rebuild a local directory (S6).

The Hugging Face repo holds one config per licence (``<config>/<split>.jsonl``, written by
``dataset.export_hf``) plus ``dataset_manifest.json`` at its root. ``resolve_hf`` downloads that
snapshot into ``.cache/pruefstand/datasets/<user>__<name>/<revision>/raw``, merges the configs into
``.../merged/<split>.jsonl`` + manifest, and ``pipeline.datasets`` then loads and validates that
directory like any local one. The snapshot is untrusted input: regular files only, capped sizes.
"""

import re
import shutil
from collections import defaultdict
from pathlib import Path

from huggingface_hub import snapshot_download

from pruefstand.core.errors import ConfigError, DatasetError
from pruefstand.pipeline.dataset_files import (
    MANIFEST_FILE,
    MAX_MANIFEST_BYTES,
    lines_of,
    open_regular,
)

CACHE_ROOT = Path(".cache/pruefstand/datasets")
"""Where snapshots live (relative to the working directory, git-ignored)."""
_PREFIX = "hf://"
_NAME = r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}"
_REF = re.compile(
    rf"(?P<user>{_NAME})/(?P<name>{_NAME})(?:@(?P<rev>[A-Za-z0-9][A-Za-z0-9_.-]{{0,127}}))?"
)
_IMMUTABLE_REV = re.compile(r"v?[0-9]+(\.[0-9]+)*")
_DONE = ".pruefstand-resolved"


def parse_hf_ref(dataset: str) -> tuple[str, str]:
    """Split ``hf://<user>/<name>[@<revision>]`` into ``(repo_id, revision)``.

    Args:
        dataset: The reference; the revision defaults to ``main``.

    Returns:
        ``("<user>/<name>", revision)``.

    Raises:
        ConfigError: The reference is malformed.

    Examples:
        >>> parse_hf_ref("hf://someone/pruefstand-de@v1")
        ('someone/pruefstand-de', 'v1')
        >>> parse_hf_ref("hf://someone/pruefstand-de")
        ('someone/pruefstand-de', 'main')
    """
    match = _REF.fullmatch(dataset.removeprefix(_PREFIX))
    if not dataset.startswith(_PREFIX) or match is None:
        msg = f"{dataset!r}: expected hf://<user>/<name>@<revision>"
        raise ConfigError(msg)
    return f"{match['user']}/{match['name']}", match["rev"] or "main"


def _download(repo_id: str, revision: str, raw: Path) -> None:
    try:
        snapshot_download(
            repo_id=repo_id, repo_type="dataset", revision=revision, local_dir=str(raw)
        )
    except Exception as exc:  # hub errors (auth, network, 404): the type only, no message
        msg = f"hf://{repo_id}@{revision}: download failed ({type(exc).__name__})"
        raise DatasetError(msg) from exc


def _merge(raw: Path, merged: Path, ref: str) -> None:
    """Concatenate ``<config>/<split>.jsonl`` over the configs into ``merged/<split>.jsonl``."""
    manifest = raw / MANIFEST_FILE
    if not manifest.is_file():
        msg = f"{ref}: the snapshot has no {MANIFEST_FILE} (re-export the dataset)"
        raise DatasetError(msg)
    with open_regular(manifest) as handle:
        data = handle.read(MAX_MANIFEST_BYTES + 1)
    if len(data) > MAX_MANIFEST_BYTES:
        msg = f"{ref}: {MANIFEST_FILE} is larger than {MAX_MANIFEST_BYTES} bytes"
        raise DatasetError(msg)
    rows: dict[str, list[bytes]] = defaultdict(list)
    for config in sorted(p for p in raw.iterdir() if p.is_dir() and not p.is_symlink()):
        if config.name.startswith("."):
            continue
        for path in sorted(config.glob("*.jsonl")):
            rows[path.stem].extend(line.rstrip(b"\r\n") for _, line in lines_of(path))
    merged.mkdir(parents=True)
    (merged / MANIFEST_FILE).write_bytes(data)
    for split, lines in rows.items():
        (merged / f"{split}.jsonl").write_bytes(b"\n".join(lines) + b"\n")


def resolve_hf(dataset: str) -> Path:
    """Download (or reuse) the snapshot of an ``hf://`` reference; return the local directory.

    A version-like revision (``v1``, ``1.0.0``) is cached: later calls make no network call.
    Any other revision (``main``, a branch) is fetched again every time.

    Args:
        dataset: ``hf://<user>/<name>@<revision>``; private repos need ``HF_TOKEN`` in the
            environment (read by ``huggingface_hub``, never by this module).

    Returns:
        The merged directory, ready for ``pipeline.datasets``.

    Raises:
        ConfigError: The reference is malformed.
        DatasetError: The download failed or the snapshot has no manifest or an unsafe file.
    """
    repo_id, revision = parse_hf_ref(dataset)
    ref = f"hf://{repo_id}@{revision}"
    base = CACHE_ROOT / repo_id.replace("/", "__") / revision
    merged = base / "merged"
    if (base / _DONE).is_file() and _IMMUTABLE_REV.fullmatch(revision):
        return merged
    shutil.rmtree(base, ignore_errors=True)
    _download(repo_id, revision, base / "raw")
    _merge(base / "raw", merged, ref)
    (base / _DONE).write_text(ref + "\n", encoding="utf-8")
    return merged

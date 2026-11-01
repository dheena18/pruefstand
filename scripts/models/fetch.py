"""Download the pinned test models and verify their SHA-256 (T1.4 S9); idempotent.

Usage: ``uv run python scripts/models/fetch.py [--manifest infra/models/test-models.yaml]
[--dest ~/.cache/pruefstand/models]``. A file that already has the right hash is not downloaded
again; a download with a wrong hash is deleted and the script fails.
"""

import argparse
import hashlib
import shutil
import urllib.request
from collections.abc import Sequence
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

DEFAULT_MANIFEST = Path("infra/models/test-models.yaml")
DEFAULT_DEST = Path("~/.cache/pruefstand/models")
CHUNK = 1 << 20
TIMEOUT_S = 60


class FetchError(Exception):
    """A download failed its integrity check."""


class ModelEntry(BaseModel):
    """One pinned model file of ``test-models.yaml``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    repo: str
    revision: str
    file: str
    url: str
    sha256: str
    size_bytes: int | None = None
    license: str


def load_models(manifest: Path) -> list[ModelEntry]:
    """Read the manifest and validate every entry."""
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    return [ModelEntry.model_validate(row) for row in data["models"]]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_file(url: str, dest: Path, sha256: str) -> str:
    """Make ``dest`` hold the file at ``url`` with the given SHA-256.

    Args:
        url: ``https://`` or ``file://`` URL.
        dest: Target file; parent directories are created.
        sha256: Expected lowercase hex digest.

    Returns:
        ``"cached"`` when ``dest`` already matched, else ``"downloaded"``.

    Raises:
        FetchError: The downloaded bytes do not match ``sha256`` (the partial file is removed).
    """
    if dest.is_file() and _sha256(dest) == sha256:
        return "cached"
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as src, part.open("wb") as out:  # noqa: S310
            shutil.copyfileobj(src, out, CHUNK)
        actual = _sha256(part)
        if actual != sha256:
            msg = f"sha256 mismatch for {url}: expected {sha256}, got {actual}"
            raise FetchError(msg)
        part.replace(dest)
    finally:
        part.unlink(missing_ok=True)
    return "downloaded"


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    args = parser.parse_args(argv)
    dest_dir = args.dest.expanduser()
    for entry in load_models(args.manifest):
        try:
            state = fetch_file(entry.url, dest_dir / entry.file, entry.sha256)
        except FetchError as err:
            print(f"fetch: {err}")
            return 1
        print(f"fetch: {entry.file} {state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

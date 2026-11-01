"""Download the pinned test models and verify their SHA-256 (T1.4 S9); idempotent.

Usage: ``uv run python scripts/models/fetch.py [--manifest infra/models/test-models.yaml]
[--dest ~/.cache/pruefstand/models]``. A file that already has the right hash is not downloaded
again; a download with a wrong hash is deleted and the script fails.
"""

import argparse
import hashlib
import os
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

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

    @model_validator(mode="after")
    def _check_pins(self) -> "ModelEntry":
        if not self.file or Path(self.file).name != self.file or self.file in {".", ".."}:
            msg = f"file '{self.file}' must be a plain file name"
            raise ValueError(msg)
        if not self.revision or self.revision not in self.url:
            msg = f"url of '{self.id}' does not contain its pinned revision"
            raise ValueError(msg)
        return self


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


def fetch_file(
    url: str,
    dest: Path,
    sha256: str,
    *,
    allowed_schemes: tuple[str, ...] = ("https",),
    size_bytes: int | None = None,
) -> str:
    """Make ``dest`` hold the file at ``url`` with the given SHA-256.

    Args:
        url: URL; only the schemes in ``allowed_schemes`` (default ``https``) are fetched.
        dest: Target file; parent directories are created.
        sha256: Expected lowercase hex digest.
        allowed_schemes: URL schemes that may be downloaded (tests add ``file``).
        size_bytes: Expected size; reading stops at ``size_bytes + 1`` bytes.

    Returns:
        ``"cached"`` when ``dest`` already matched, else ``"downloaded"``.

    Raises:
        FetchError: Scheme not allowed, ``.part`` target is a symlink, the download is larger
            than ``size_bytes``, or its bytes do not match ``sha256`` (partial file removed).
    """
    if urlparse(url).scheme not in allowed_schemes:
        msg = f"URL scheme of {url!r} is not allowed (allowed: {', '.join(allowed_schemes)})"
        raise FetchError(msg)
    if dest.is_file() and _sha256(dest) == sha256:
        return "cached"
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    if part.is_symlink():
        msg = f"{part} is a symlink; refusing to write through it"
        raise FetchError(msg)
    part.unlink(missing_ok=True)
    try:
        _download(url, part, size_bytes)
        actual = _sha256(part)
        if actual != sha256:
            msg = f"sha256 mismatch for {url}: expected {sha256}, got {actual}"
            raise FetchError(msg)
        part.replace(dest)
    finally:
        part.unlink(missing_ok=True)
    return "downloaded"


def _download(url: str, part: Path, size_bytes: int | None) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    limit = None if size_bytes is None else size_bytes + 1
    total = 0
    with (
        urllib.request.urlopen(url, timeout=TIMEOUT_S) as src,  # noqa: S310  (scheme checked by caller)
        os.fdopen(os.open(part, flags, 0o600), "wb") as out,
    ):
        while chunk := src.read(CHUNK if limit is None else min(CHUNK, limit - total)):
            total += len(chunk)
            if size_bytes is not None and total > size_bytes:
                msg = f"download of {url} is larger than the pinned size {size_bytes}"
                raise FetchError(msg)
            out.write(chunk)
            if limit is not None and total >= limit:
                break


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    parser.add_argument(
        "--allow-scheme", action="append", default=None, help="extra URL scheme (tests only)"
    )
    args = parser.parse_args(argv)
    dest_dir = args.dest.expanduser()
    for entry in load_models(args.manifest):
        try:
            state = fetch_file(
                entry.url,
                dest_dir / entry.file,
                entry.sha256,
                allowed_schemes=tuple(args.allow_scheme or ["https"]),
                size_bytes=entry.size_bytes,
            )
        except FetchError as err:
            print(f"fetch: {err}")
            return 1
        print(f"fetch: {entry.file} {state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

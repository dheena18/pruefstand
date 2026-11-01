"""Download the pinned test models and verify their SHA-256 (T1.4 S9); idempotent.

Usage: ``uv run python scripts/models/fetch.py [--manifest infra/models/test-models.yaml]
[--dest ~/.cache/pruefstand/models]``. A file that already has the right hash is not downloaded
again; a download with a wrong hash is deleted and the script fails.
"""

import argparse
import hashlib
import os
import re
import time
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
DEADLINE_S = 3600.0
DEFAULT_MAX_BYTES = 8 * 1024**3
_REVISION = re.compile(r"[0-9a-f]{40}")


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
        if not _REVISION.fullmatch(self.revision) or self.revision not in self.url:
            msg = f"revision of '{self.id}' must be a 40-hex commit hash that the url contains"
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


class _SchemeRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to the schemes the caller allows."""

    def __init__(self, allowed: tuple[str, ...]) -> None:
        self._allowed = allowed

    def redirect_request(  # noqa: PLR0917  (signature fixed by urllib)
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        if urlparse(newurl).scheme not in self._allowed:
            message = f"redirect to scheme {urlparse(newurl).scheme!r} refused"
            raise FetchError(message)
        return super().redirect_request(req, fp, code, msg, headers, newurl)  # type: ignore[arg-type]


def fetch_file(
    url: str,
    dest: Path,
    sha256: str,
    *,
    allowed_schemes: tuple[str, ...] = ("https",),
    size_bytes: int | None = None,
    deadline_s: float = DEADLINE_S,
    default_max_bytes: int = DEFAULT_MAX_BYTES,
) -> str:
    """Make ``dest`` hold the file at ``url`` with the given SHA-256.

    Args:
        url: URL; only the schemes in ``allowed_schemes`` (default ``https``) are fetched.
        dest: Target file; parent directories are created.
        sha256: Expected lowercase hex digest.
        allowed_schemes: URL schemes that may be downloaded (tests add ``file``).
        size_bytes: Expected size; reading stops at ``size_bytes + 1`` bytes.
        deadline_s: Total time allowed for the download.
        default_max_bytes: Size cap when ``size_bytes`` is None.

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
        _download(
            url,
            part,
            size_bytes=size_bytes,
            deadline_s=deadline_s,
            default_max_bytes=default_max_bytes,
            allowed=allowed_schemes,
        )
        actual = _sha256(part)
        if actual != sha256:
            msg = f"sha256 mismatch for {url}: expected {sha256}, got {actual}"
            raise FetchError(msg)
        part.replace(dest)
    finally:
        part.unlink(missing_ok=True)
    return "downloaded"


def _download(
    url: str,
    part: Path,
    *,
    size_bytes: int | None,
    deadline_s: float,
    default_max_bytes: int,
    allowed: tuple[str, ...],
) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    cap = size_bytes if size_bytes is not None else default_max_bytes
    deadline = time.monotonic() + deadline_s
    total = 0
    with (
        urllib.request.build_opener(_SchemeRedirects(allowed)).open(url, timeout=TIMEOUT_S) as src,
        os.fdopen(os.open(part, flags, 0o600), "wb") as out,
    ):
        while chunk := src.read(min(CHUNK, cap + 1 - total)):
            total += len(chunk)
            if total > cap:
                msg = f"download of {url} is larger than the allowed size {cap}"
                raise FetchError(msg)
            if time.monotonic() > deadline:
                msg = f"download of {url} passed its deadline of {deadline_s:g} s"
                raise FetchError(msg)
            out.write(chunk)


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

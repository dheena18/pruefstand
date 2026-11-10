"""Fetching and licence checks of the data downloader (T2.1): HTTP, Hugging Face, GitHub.

HTTP downloads are resumable (``<file>.part`` + ``Range``), retried with backoff and never try to
get around a bot challenge. Hugging Face datasets come from ``snapshot_download`` at the pinned
commit into ``data/raw/hf/<id>/``; the licence is read from the dataset card and compared with
``sources.yaml`` before anything is downloaded.
"""

import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from data_hf import sync_hf
from data_sources import (
    ChecksumError,
    FetchError,
    LicenseMismatch,
    Source,
    SyncResult,
    sha256_file,
)

VERSION = "0.1"
REPO_URL = "https://github.com/dheena18/pruefstand"
USER_AGENT = f"pruefstand-data/{VERSION} (+{REPO_URL})"
GII_URL = "https://www.gesetze-im-internet.de/{slug}/xml.zip"
GII_MIRROR_ENV = "PRUEFSTAND_GII_MIRROR"
GII_MIRROR_FILE = "{slug}.xml.zip"
# EUR-Lex itself sits behind a bot challenge; the Publications Office CELLAR serves the same act
# (official XHTML rendition) by CELEX with content negotiation (owner decision, T2.1).
CELLAR_URL = "https://publications.europa.eu/resource/celex/{celex}"
CELLAR_LANGS = {"de": "deu", "en": "eng"}
GITHUB_RAW = "https://raw.githubusercontent.com/{repo}/{commit}/{path}"
ATTEMPTS = 4
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
TIMEOUT = httpx.Timeout(60.0, connect=20.0)
LICENSE_MARKERS = (
    ("attribution-noncommercial 4.0", "cc-by-nc-4.0"),
    ("attribution-sharealike 4.0", "cc-by-sa-4.0"),
    ("attribution 4.0 international", "cc-by-4.0"),
    ("apache license", "apache-2.0"),
    ("open database license", "odbl"),
    ("mit license", "mit"),
)
Sleep = Callable[[float], None]


def make_client() -> httpx.Client:
    """Return the shared HTTP client (User-Agent, redirects, at most 4 connections)."""
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=TIMEOUT,
        limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
    )


def detect_license(text: str) -> str:
    """Map the head of a LICENSE file to an SPDX-like id (``unknown`` if not recognised)."""
    head = text[:600].lower()
    for marker, spdx in LICENSE_MARKERS:
        if marker in head:
            return spdx
    return "unknown"


def _attempt(
    client: httpx.Client, url: str, part: Path, extra: dict[str, str] | None = None
) -> bool:
    """Run one download attempt into ``part``; return False if it should be retried."""
    offset = part.stat().st_size if part.exists() else 0
    headers = dict(extra or {})
    if offset:
        headers["Range"] = f"bytes={offset}-"
    with client.stream("GET", url, headers=headers) as resp:
        if resp.status_code in RETRY_STATUS:
            return False
        if resp.status_code == 416:  # stale partial file: start again
            part.unlink(missing_ok=True)
            return False
        if resp.headers.get("x-amzn-waf-action") or resp.status_code == 202:
            msg = (
                f"{url}: HTTP {resp.status_code}, anti-bot challenge "
                "(x-amzn-waf-action); not bypassed, see data/README.md"
            )
            raise FetchError(msg)
        if resp.status_code >= 400:
            msg = f"{url}: HTTP {resp.status_code}"
            raise FetchError(msg)
        append = resp.status_code == 206 and offset > 0
        with part.open("ab" if append else "wb") as out:
            for chunk in resp.iter_bytes():
                out.write(chunk)
    return True


def fetch_file(
    client: httpx.Client,
    url: str,
    dest: Path,
    *,
    sleep: Sleep = time.sleep,
    headers: dict[str, str] | None = None,
) -> None:
    """Download ``url`` to ``dest`` (resumable, retried with exponential backoff).

    Raises:
        FetchError: HTTP error, bot challenge, or attempts exhausted.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    for attempt in range(ATTEMPTS):
        try:
            if _attempt(client, url, part, headers):
                part.replace(dest)
                return
        except httpx.TransportError:
            pass
        sleep(2.0**attempt)
    msg = f"{url}: failed after {ATTEMPTS} attempts"
    raise FetchError(msg)


def request_headers(src: Source, name: str) -> dict[str, str]:
    """Content-negotiation headers: CELLAR picks the language from Accept-Language."""
    if src.kind != "eurlex":
        return {}
    lang = CELLAR_LANGS[name.removesuffix(".html")]
    return {"Accept": "text/html, application/xhtml+xml", "Accept-Language": lang}


def _gii_url(slug: str | None) -> str:
    """URL of a GII archive: the official site, or ``$PRUEFSTAND_GII_MIRROR/<slug>.xml.zip``.

    The mirror (a release of the public repo holding the same bytes) exists because the official
    site refuses GitHub-hosted runners. The pinned SHA-256 is checked either way, so a mirror
    cannot change content.

    >>> _gii_url("kschg")
    'https://www.gesetze-im-internet.de/kschg/xml.zip'
    """
    mirror = os.environ.get(GII_MIRROR_ENV, "").strip()
    if not mirror:
        return GII_URL.format(slug=slug)
    if not mirror.startswith("https://"):
        msg = f"{GII_MIRROR_ENV} must be an https:// URL, got {mirror[:60]!r}"
        raise FetchError(msg)
    return f"{mirror.rstrip('/')}/{GII_MIRROR_FILE.format(slug=slug)}"


def http_urls(src: Source) -> dict[str, str]:
    """Return ``{file name: URL}`` for the HTTP-served kinds (gii, eurlex, github)."""
    if src.kind == "gii":
        return {name: _gii_url(src.slug) for name in src.files}
    if src.kind == "eurlex":
        return {name: CELLAR_URL.format(celex=src.celex) for name in src.files}
    return {
        name: GITHUB_RAW.format(repo=src.repo, commit=src.commit, path=name) for name in src.files
    }


def _sync_files(
    src: Source,
    base: Path,
    urls: dict[str, str],
    result: SyncResult,
    *,
    client: httpx.Client,
    sleep: Sleep,
    pin_check: bool,
) -> None:
    for name, url in urls.items():
        target = base / name
        pin = src.files[name] if pin_check else None
        if pin_check and target.is_file() and pin and sha256_file(target) == pin:
            result.files[name] = pin
            continue
        fetch_file(client, url, target, sleep=sleep, headers=request_headers(src, name))
        result.downloads += 1
        actual = sha256_file(target)
        if pin and actual != pin:
            target.unlink()
            raise ChecksumError(src.id, name, pin, actual)
        if pin is None and pin_check:
            result.unpinned.append(name)
        result.files[name] = actual


def check_github_license(src: Source, base: Path) -> None:
    """Compare the fetched ``LICENSE`` file with ``sources.yaml``.

    Raises:
        LicenseMismatch: LICENSE missing from the pins, or it names another licence.
    """
    path = base / "LICENSE"
    if not path.is_file():
        raise LicenseMismatch(src.id, src.license, "no LICENSE file pinned")
    found = detect_license(path.read_text(encoding="utf-8", errors="replace"))
    if found != src.license:
        raise LicenseMismatch(src.id, src.license, found)


def _sync_http(
    src: Source, root: Path, *, client: httpx.Client, sleep: Sleep, pin_check: bool
) -> SyncResult:
    result = SyncResult()
    base = root / src.rel_dir
    urls = http_urls(src)
    opts: dict[str, Any] = {"client": client, "sleep": sleep, "pin_check": pin_check}
    if src.kind == "github":  # LICENSE first: a mismatch stops before any data is fetched
        lic = {k: v for k, v in urls.items() if k == "LICENSE"}
        _sync_files(src, base, lic, result, **opts)
        check_github_license(src, base)
        urls = {k: v for k, v in urls.items() if k != "LICENSE"}
    _sync_files(src, base, urls, result, **opts)
    return result


def sync_source(
    src: Source,
    root: Path,
    *,
    client: httpx.Client,
    sleep: Sleep = time.sleep,
    pin_check: bool = True,
) -> SyncResult:
    """Download one source into ``root/<rel_dir>`` unless valid files are already there.

    Args:
        src: The pinned source.
        root: ``data/raw``.
        client: Shared HTTP client (``make_client``).
        sleep: Backoff sleeper (replaced in tests).
        pin_check: False for ``--update-pins``: always re-download, never compare to the pin.

    Returns:
        Computed hashes, number of downloads and names that still have no pin.

    Raises:
        ChecksumError: A file differs from its pin.
        LicenseMismatch: Upstream licence differs from ``sources.yaml``.
        ConfigMissingError: The pinned Hugging Face config does not exist.
        FetchError: Download failed or a pinned file is absent upstream.
    """
    if src.kind == "hf":
        return sync_hf(src, root, pin_check=pin_check, sleep=sleep)
    return _sync_http(src, root, client=client, sleep=sleep, pin_check=pin_check)

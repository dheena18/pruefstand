"""Hugging Face part of the downloader (T2.1): card licence/config checks and pinned snapshots.

The licence is read from the dataset card on the default branch and compared with
``sources.yaml`` before anything is downloaded; files come from ``snapshot_download`` at the
pinned commit into ``data/raw/hf/<id>/`` (never from the HF cache).
"""

import time
from collections.abc import Callable
from pathlib import Path

import httpx
from data_sources import (
    ChecksumError,
    ConfigMissingError,
    FetchError,
    LicenseMismatch,
    Source,
    SyncResult,
    sha256_file,
)
from huggingface_hub import dataset_info, snapshot_download
from huggingface_hub.errors import HfHubHTTPError

ATTEMPTS = 4
NO_RETRY_STATUS = frozenset({401, 403, 404})
Sleep = Callable[[float], None]


def _status(err: Exception) -> int | None:
    response = getattr(err, "response", None)
    code = getattr(response, "status_code", None)
    return code if isinstance(code, int) else None


def _with_retry[T](src: Source, call: Callable[[], T], sleep: Sleep) -> T:
    """Run a Hub call with backoff; failures become a FetchError naming only the exception class.

    Local filesystem errors (an ``OSError`` with an errno that is not an HTTP error) are not
    retried and are reported as local, not as Hub failures.
    """
    for attempt in range(ATTEMPTS):
        try:
            return call()
        except (httpx.HTTPError, OSError, HfHubHTTPError) as err:
            errno = getattr(err, "errno", None)
            if errno is not None and not isinstance(err, (httpx.HTTPError, HfHubHTTPError)):
                name = type(err).__name__
                msg = f"{src.id}: local file error while fetching ({name}, errno {errno})"
                raise FetchError(msg) from None
            if _status(err) in NO_RETRY_STATUS or attempt == ATTEMPTS - 1:
                msg = f"{src.id}: Hugging Face request failed ({type(err).__name__})"
                if _status(err) in (401, 403):
                    msg += "; gated datasets need HF_TOKEN of an account that accepted the terms"
                raise FetchError(msg) from None
            sleep(2.0**attempt)
    raise AssertionError  # pragma: no cover  # loop always returns or raises


def _card_attr(info: object, name: str) -> object:
    return getattr(getattr(info, "card_data", None), name, None)


def _card_license(info: object) -> str:
    value = _card_attr(info, "license")
    if isinstance(value, list):
        value = ",".join(str(v) for v in value)
    return str(value).lower() if value else "none"


def check_hf_license(src: Source, info: object | None = None, sleep: Sleep = time.sleep) -> None:
    """Compare the dataset-card ``license`` field with ``sources.yaml``.

    Args:
        src: A ``hf`` source.
        info: Result of ``dataset_info`` (fetched when omitted).
        sleep: Backoff sleeper (replaced in tests).

    Raises:
        LicenseMismatch: Card licence differs from the pinned one.
    """
    info = info or _with_retry(src, lambda: dataset_info(str(src.repo_id)), sleep)
    actual = _card_license(info)
    # card_license documents one known deviation of the card from the real licence (see
    # DATA_LICENSES.md section 7); the card must then say exactly that value.
    expected = (src.card_license or src.license).lower()
    if actual != expected:
        raise LicenseMismatch(src.id, expected, actual)


def check_hf_config(src: Source, info: object) -> None:
    """Fail with the list of existing configs when the pinned config is not in the dataset.

    Raises:
        ConfigMissingError: ``src.config`` is not one of the card's configs.
    """
    if not src.config:
        return
    configs = _card_attr(info, "configs")
    entries = configs if isinstance(configs, list) else []
    names = [str(c["config_name"]) for c in entries if isinstance(c, dict) and "config_name" in c]
    if src.config not in names:
        raise ConfigMissingError(src.id, src.config, names)


def latest_hf_revision(src: Source, sleep: Sleep = time.sleep) -> str:
    """Return the current commit SHA of the dataset (of ``ref`` when set); used by update-pins."""
    info = _with_retry(src, lambda: dataset_info(str(src.repo_id), revision=src.ref), sleep)
    return str(info.sha)


def _hf_valid(src: Source, base: Path) -> bool:
    return all(
        (base / n).is_file() and sha is not None and sha256_file(base / n) == sha
        for n, sha in src.files.items()
    )


def sync_hf(src: Source, root: Path, *, pin_check: bool, sleep: Sleep = time.sleep) -> SyncResult:
    """Check licence and config, then snapshot the pinned files unless they are already valid.

    Raises:
        LicenseMismatch: Card licence differs from sources.yaml.
        ConfigMissingError: The pinned config does not exist.
        ChecksumError: A file differs from its pin.
        FetchError: Gated/refused by the Hub, or a pinned file is absent upstream.
    """
    info = _with_retry(src, lambda: dataset_info(str(src.repo_id)), sleep)
    check_hf_license(src, info)
    check_hf_config(src, info)
    base = root / src.rel_dir
    result = SyncResult()
    if pin_check and _hf_valid(src, base):
        result.files = {n: str(s) for n, s in src.files.items()}
        return result
    _with_retry(
        src,
        lambda: snapshot_download(
            repo_id=str(src.repo_id),
            repo_type="dataset",
            revision=src.revision,
            local_dir=str(base),
            allow_patterns=list(src.files),
        ),
        sleep,
    )
    result.downloads = len(src.files)
    for name, pin in src.files.items():
        path = base / name
        if not path.is_file():
            msg = f"{src.id}: {name} not found in {src.repo_id}@{src.revision}"
            raise FetchError(msg)
        actual = sha256_file(path)
        if pin_check and pin and actual != pin:
            path.unlink()
            raise ChecksumError(src.id, name, pin, actual)
        if pin_check and pin is None:
            result.unpinned.append(name)
        result.files[name] = actual
    return result

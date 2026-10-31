"""Hugging Face part of the downloader (T2.1): card licence/config checks and pinned snapshots.

The licence is read from the dataset card on the default branch and compared with
``sources.yaml`` before anything is downloaded; files come from ``snapshot_download`` at the
pinned commit into ``data/raw/hf/<id>/`` (never from the HF cache).
"""

from pathlib import Path

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


def _card_attr(info: object, name: str) -> object:
    return getattr(getattr(info, "card_data", None), name, None)


def _card_license(info: object) -> str:
    value = _card_attr(info, "license")
    if isinstance(value, list):
        value = ",".join(str(v) for v in value)
    return str(value).lower() if value else "none"


def check_hf_license(src: Source, info: object | None = None) -> None:
    """Compare the dataset-card ``license`` field with ``sources.yaml``.

    Args:
        src: A ``hf`` source.
        info: Result of ``dataset_info`` (fetched when omitted).

    Raises:
        LicenseMismatch: Card licence differs from the pinned one.
    """
    info = info or dataset_info(str(src.repo_id))
    actual = _card_license(info)
    if actual != src.license.lower():
        raise LicenseMismatch(src.id, src.license, actual)


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


def latest_hf_revision(src: Source) -> str:
    """Return the current commit SHA of the dataset (of ``ref`` when set); used by update-pins."""
    return str(dataset_info(str(src.repo_id), revision=src.ref).sha)


def _hf_valid(src: Source, base: Path) -> bool:
    return all(
        (base / n).is_file() and sha is not None and sha256_file(base / n) == sha
        for n, sha in src.files.items()
    )


def sync_hf(src: Source, root: Path, *, pin_check: bool) -> SyncResult:
    """Check licence and config, then snapshot the pinned files unless they are already valid.

    Raises:
        LicenseMismatch: Card licence differs from sources.yaml.
        ConfigMissingError: The pinned config does not exist.
        ChecksumError: A file differs from its pin.
        FetchError: Gated/refused by the Hub, or a pinned file is absent upstream.
    """
    info = dataset_info(str(src.repo_id))
    check_hf_license(src, info)
    check_hf_config(src, info)
    base = root / src.rel_dir
    result = SyncResult()
    if pin_check and _hf_valid(src, base):
        result.files = {n: str(s) for n, s in src.files.items()}
        return result
    try:
        snapshot_download(
            repo_id=str(src.repo_id),
            repo_type="dataset",
            revision=src.revision,
            local_dir=str(base),
            allow_patterns=list(src.files),
        )
    except HfHubHTTPError as err:
        msg = (
            f"{src.id}: Hugging Face refused {src.repo_id}@{src.revision} ({type(err).__name__}); "
            "gated datasets need HF_TOKEN of an account that accepted the terms"
        )
        raise FetchError(msg) from err
    result.downloads = len(src.files)
    for name, pin in src.files.items():
        path = base / name
        if not path.is_file():
            msg = f"{src.id}: {name} not found in {src.repo_id}@{src.revision}"
            raise FetchError(msg)
        actual = sha256_file(path)
        if pin_check and pin and actual != pin:
            raise ChecksumError(src.id, name, pin, actual)
        if pin_check and pin is None:
            result.unpinned.append(name)
        result.files[name] = actual
    return result

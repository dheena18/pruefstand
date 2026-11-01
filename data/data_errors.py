"""Error types of the data downloader (T2.1); each carries its process exit code."""


class DataError(Exception):
    """Base class of downloader failures; ``exit_code`` is the process exit code."""

    exit_code = 1


class ChecksumError(DataError):
    """A file's SHA-256 differs from the pin."""

    def __init__(self, source_id: str, name: str, expected: str, actual: str) -> None:
        super().__init__(
            f"checksum mismatch: {source_id}/{name} expected {expected} actual {actual}"
        )


class LicenseMismatch(DataError):  # noqa: N818  # name fixed by the T2.1 prompt (exit 3)
    """The licence found upstream differs from sources.yaml."""

    exit_code = 3

    def __init__(self, source_id: str, expected: str, actual: str) -> None:
        super().__init__(
            f"license mismatch: {source_id}: sources.yaml says {expected!r}, upstream: {actual!r}"
        )


class ConfigMissingError(DataError):
    """The pinned Hugging Face config does not exist in the dataset."""

    exit_code = 2

    def __init__(self, source_id: str, config: str, available: list[str]) -> None:
        super().__init__(
            f"config missing: {source_id} has no config {config!r}; available: {sorted(available)}"
        )


class FetchError(DataError):
    """A download failed (HTTP error, bot challenge, missing file after download)."""


class SourcesError(DataError):
    """``sources.yaml`` is malformed."""

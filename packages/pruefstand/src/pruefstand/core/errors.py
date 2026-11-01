"""Error hierarchy (interfaces §2); every Prüfstand error derives from ``PruefstandError``."""


class PruefstandError(Exception):
    """Base class of all Prüfstand errors."""


class ConfigError(PruefstandError):
    """A configuration is invalid or inconsistent."""


class TargetError(PruefstandError):
    """The system under test failed to answer.

    Args:
        message: Human-readable reason.
        transient: True when a retry may succeed (timeout, 5xx); False for permanent failures.
    """

    def __init__(self, message: str = "", *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


class LLMError(PruefstandError):
    """An LLM call failed.

    Args:
        message: Human-readable reason; never contains a secret.
        transient: True when a retry may succeed (timeout, connection loss, 429, 5xx).
        status: HTTP status of the provider answer, when there was one.
    """

    def __init__(
        self, message: str = "", *, transient: bool = False, status: int | None = None
    ) -> None:
        super().__init__(message)
        self.transient = transient
        self.status = status


class PolicyViolation(LLMError):  # noqa: N818  (name fixed by interfaces §2)
    """An LLM call was refused by ``LLMPolicy`` (provider or data not allowed)."""


class BudgetExceeded(PruefstandError):  # noqa: N818  (name fixed by interfaces §2)
    """A USD or token budget would be exceeded."""


class QuotaExhausted(LLMError):  # noqa: N818  (name fixed by interfaces §2)
    """A provider quota is exhausted (GitHub Models 429); raised by ``LLMClient``."""


class DatasetError(PruefstandError):
    """A dataset file or manifest is invalid."""


class StoreError(PruefstandError):
    """A run or baseline store operation failed."""


class StoreIntegrityError(StoreError):
    """A stored file does not match the SHA-256 recorded for it (corrupt or tampered)."""


class GateInputError(PruefstandError):
    """The gate cannot decide on the given inputs (incomplete run, fingerprint mismatch)."""


class PromptError(PruefstandError):
    """A prompt file is missing, malformed or its version is wrong."""


class CorpusMismatch(PruefstandError):  # noqa: N818  (name fixed by interfaces §2)
    """The target serves a different corpus version than the dataset was built for."""

"""The JSON error body of every public-mode 4xx/5xx (interfaces section 16, D138).

``{"code", "message", "retry_after_s"}`` with a fixed set of codes and statuses. The message is
English, fixed per code and never contains the question, a stack trace or a path.
"""

from dataclasses import dataclass
from typing import Literal

Code = Literal[
    "rate_limited",
    "daily_limit",
    "busy",
    "budget_exhausted",
    "demo_disabled",
    "invalid_request",
    "body_too_large",
    "timeout",
]

STATUS: dict[Code, int] = {
    "rate_limited": 429,
    "daily_limit": 429,
    "busy": 429,
    "budget_exhausted": 503,
    "demo_disabled": 503,
    "invalid_request": 422,
    "body_too_large": 413,
    "timeout": 504,
}
MESSAGES: dict[Code, str] = {
    "rate_limited": "Too many requests; please slow down.",
    "daily_limit": "The daily request limit is reached.",
    "busy": "The demo is busy; please try again in a few seconds.",
    "budget_exhausted": "The daily demo budget is used up.",
    "demo_disabled": "The demo is switched off.",
    "invalid_request": "The request is not valid.",
    "body_too_large": "The request body is too large.",
    "timeout": "The answer took too long.",
}
BUSY_RETRY_S = 5


@dataclass(frozen=True)
class Rejection:
    """A refused request: what the client is told.

    Attributes:
        code: The error code.
        retry_after_s: Whole seconds after which a retry makes sense, or ``None``.
    """

    code: Code
    retry_after_s: int | None = None

    @property
    def status(self) -> int:
        """The HTTP status of ``code``."""
        return STATUS[self.code]

    def body(self) -> dict[str, object]:
        """The response body: exactly ``code``, ``message`` and ``retry_after_s``."""
        return error_body(self.code, self.retry_after_s)

    def headers(self) -> dict[str, str]:
        """``Retry-After`` for other clients (the UI reads the body)."""
        return {} if self.retry_after_s is None else {"Retry-After": str(self.retry_after_s)}


def error_body(code: Code, retry_after_s: int | None = None) -> dict[str, object]:
    """Build the error body of ``code``.

    >>> sorted(error_body("busy", 5))
    ['code', 'message', 'retry_after_s']
    >>> error_body("busy", 5)["retry_after_s"]
    5
    """
    return {"code": code, "message": MESSAGES[code], "retry_after_s": retry_after_s}

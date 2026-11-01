"""One scanner for secret-looking text; cassette recording refuses whatever it finds."""

import re

from pruefstand.core.errors import LLMError

SECRET_PATTERN = re.compile(
    r"sk-[A-Za-z0-9]{8,}|gh[pousr]_|github_pat_|hf_[A-Za-z0-9]{8,}|Bearer\s+\S{8,}|eyJ[A-Za-z0-9_-]{10,}"
)


def assert_no_secrets(text: str) -> None:
    """Refuse text that looks like it holds a token, key or credential header.

    Args:
        text: Anything about to be written to a cassette (URL, headers, body, JSON file).

    Raises:
        LLMError: ``text`` matches ``SECRET_PATTERN``; the message never repeats the match.

    Examples:
        >>> assert_no_secrets("Die Kündigung muss schriftlich erfolgen.")
        >>> assert_no_secrets("Authorization: Bearer abcdefgh12345")
        Traceback (most recent call last):
        ...
        pruefstand.core.errors.LLMError: recording refused: the text looks like a secret
    """
    if SECRET_PATTERN.search(text):
        msg = "recording refused: the text looks like a secret"
        raise LLMError(msg, transient=False)

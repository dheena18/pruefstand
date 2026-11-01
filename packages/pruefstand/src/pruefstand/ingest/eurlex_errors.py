"""Errors of the EUR-Lex parser (T2.4)."""

from pruefstand.core.errors import DatasetError

TOO_LARGE = "too_large"
INVALID_ENCODING = "invalid_encoding"
INVALID_HTML = "invalid_html"
TOO_DEEP = "too_deep"
TOO_MANY_ELEMENTS = "too_many_elements"
NO_ARTICLES = "no_articles"
TOO_MUCH_TEXT = "too_much_text"


class EurLexParseError(DatasetError):
    """A file could not be read safely.

    Attributes:
        kind: ``too_large``, ``invalid_encoding``, ``invalid_html``, ``too_deep``,
            ``too_many_elements``, ``too_much_text`` or ``no_articles``.
        detail: Human-readable detail.
    """

    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail

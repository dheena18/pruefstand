"""Errors of the GII loader. All derive from :class:`pruefstand.core.errors.PruefstandError`."""

from pruefstand.core.errors import PruefstandError


class GiiError(PruefstandError):
    """Base class of every GII loader error."""


class UnsafeArchiveError(GiiError):
    """The zip archive is malformed or breaks a safety limit (zip-slip, symlink, bomb, size)."""


class UnsafeXmlError(GiiError):
    """The XML breaks a safety rule (entity declarations, nesting depth, size, encoding)."""


class GiiParseError(GiiError):
    """The XML is not well-formed."""


class CitationKeyError(GiiError, ValueError):
    """No citation key can be built for a norm (unknown law or unparsable number)."""

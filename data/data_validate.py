"""Schema validation of data/sources.yaml (T2.1): types, licence allow-set, config rules."""

import re
from typing import TYPE_CHECKING, Any

from data_errors import SourcesError

if TYPE_CHECKING:
    from data_sources import Source

KINDS = ("gii", "hf", "eurlex", "github")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
ID_RE = re.compile(r"(?:(?:gii|eurlex):[A-Za-z0-9]+|[a-z0-9_]+)\Z")
# Every licence a source may declare; anything else (typos, other spellings) fails loudly.
ALLOWED_LICENSES = frozenset(
    {
        "official-work-5-urhg",
        "eurlex-legal-notice",
        "odbl",
        "cc-by-4.0",
        "cc-by-sa-4.0",
        "apache-2.0",
        "cc-by-nc-4.0",
    }
)
# A dataset config holds exactly one licence (ODbL, CC BY and CC BY-SA never share a config,
# ADR-0015), except where this table lists the licences it may hold together.
CONFIG_LICENSES: dict[str, frozenset[str]] = {
    "laws_eurlex": frozenset({"official-work-5-urhg", "eurlex-legal-notice"}),
}
DOWNLOAD_ONLY = "download_only"
# The closed set of dataset configs (DATA_LICENSES.md section 2, plus download_only for MEMERAG).
KNOWN_CONFIGS = frozenset(
    {
        "laws_eurlex",
        "oldp_derived",
        "germanquad_derived",
        "germanrag_derived",
        "own",
        DOWNLOAD_ONLY,
    }
)
CONFIG_RE = re.compile(r"[a-z][a-z0-9_]*\Z")
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+\Z")
STR_FIELDS = ("id", "kind", "license", "license_config", "attribution")
OPTIONAL_STR_FIELDS = (
    "abbrev", "slug", "celex", "pinned", "repo_id", "config", "revision", "ref", "card_license",
    "repo", "commit",
)  # fmt: skip
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def check_types(source_id: object, fields: dict[str, Any]) -> None:
    """Reject non-str / non-bool values before they reach dataclass construction or hashing."""
    label = source_id if isinstance(source_id, str) else repr(source_id)
    for name in STR_FIELDS:
        if not isinstance(fields.get(name), str):
            msg = f"{label}: field {name!r} must be a string"
            raise SourcesError(msg)
    for name in OPTIONAL_STR_FIELDS:
        if fields.get(name) is not None and not isinstance(fields[name], str):
            msg = f"{label}: field {name!r} must be a string"
            raise SourcesError(msg)
    if not isinstance(fields.get("redistribute"), bool):
        msg = f"{label}: redistribute must be a boolean (true or false)"
        raise SourcesError(msg)
    if not isinstance(fields.get("files"), dict):
        msg = f"{label}: files must be a mapping"
        raise SourcesError(msg)


def _validate_licence(source: "Source") -> None:
    if not CONFIG_RE.match(source.license_config) or source.license_config not in KNOWN_CONFIGS:
        msg = (
            f"{source.id}: license_config {source.license_config!r} not in {sorted(KNOWN_CONFIGS)}"
        )
        raise SourcesError(msg)
    if source.license not in ALLOWED_LICENSES:
        msg = (
            f"{source.id}: unknown licence {source.license!r}; allowed: {sorted(ALLOWED_LICENSES)}"
        )
        raise SourcesError(msg)
    download_only = source.license_config == DOWNLOAD_ONLY
    if source.license == "cc-by-nc-4.0" and not download_only:
        msg = f"{source.id}: non-commercial data belongs in license_config {DOWNLOAD_ONLY}"
        raise SourcesError(msg)
    if download_only == source.redistribute:
        msg = f"{source.id}: redistribute must be false exactly for license_config {DOWNLOAD_ONLY}"
        raise SourcesError(msg)


def validate_source(source: "Source") -> None:
    """Validate one source: id, kind, pins, licence, config, file names and checksums.

    Raises:
        SourcesError: Any rule is violated.
    """
    if not ID_RE.match(source.id):
        msg = f"bad source id {source.id!r}"
        raise SourcesError(msg)
    if source.kind not in KINDS:
        msg = f"{source.id}: unknown kind {source.kind!r}"
        raise SourcesError(msg)
    if source.kind == "hf" and not (source.revision and HEX40.match(source.revision)):
        msg = f"{source.id}: hf revision must be a 40-hex commit SHA"
        raise SourcesError(msg)
    if source.kind == "github" and not (source.commit and HEX40.match(source.commit)):
        msg = f"{source.id}: github commit must be a 40-hex SHA"
        raise SourcesError(msg)
    for field_name, needed in (("slug", "gii"), ("celex", "eurlex")):
        value = getattr(source, field_name)
        if (source.kind == needed and value is None) or (
            value is not None and not TOKEN_RE.match(value)
        ):
            msg = f"{source.id}: {field_name} must match [A-Za-z0-9_]+"
            raise SourcesError(msg)
    _validate_licence(source)
    for name, sha in source.files.items():
        parts = name.split("/")
        bad_char = any(ord(c) < 32 or ord(c) == 127 for c in name)
        if (
            bad_char
            or name.endswith(".part")
            or "\\" in name
            or any(p in ("", ".", "..") for p in parts)
        ):
            msg = f"{source.id}: file name {name!r} must be a clean relative path"
            raise SourcesError(msg)
        if sha is not None and not HEX64.match(sha):
            msg = f"{source.id}/{name}: sha256 must be 64 lowercase hex characters"
            raise SourcesError(msg)


def check_config_homogeneity(sources: "list[Source]") -> None:
    """Fail when a config holds more licences than allowed (ADR-0015).

    Every config holds exactly one licence, except those listed in ``CONFIG_LICENSES``.
    """
    by_config: dict[str, set[str]] = {}
    for src in sources:
        by_config.setdefault(src.license_config, set()).add(src.license)
    for config, licences in by_config.items():
        allowed = CONFIG_LICENSES.get(config)
        if (allowed is not None and not licences <= allowed) or (
            allowed is None and len(licences) > 1
        ):
            msg = f"config {config!r} may not hold licences {sorted(licences)}"
            raise SourcesError(msg)

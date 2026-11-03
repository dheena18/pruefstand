"""Licence configs of the dataset (SPEC §2.4, ``DATA_LICENSES.md`` §2/§3, ADR-0015).

Every ``TestCase`` has exactly one ``license_config``. There is no "most restrictive" rule: ODbL
never mixes with another share-alike licence, so a case needing two configs is dropped by the
builder and flagged by ``validate_dataset``.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class LicenseInfo:
    """Licence of one Hugging Face config.

    Attributes:
        spdx: HF card licence id (``cc-by-4.0``).
        name: Human-readable licence name for the manifest and the card.
        attribution: Attribution text of the sources (``DATA_LICENSES.md`` §3).
    """

    spdx: str
    name: str
    attribution: str


_GII = (
    "Gesetzestexte: Bundesministerium der Justiz / juris GmbH, www.gesetze-im-internet.de. "
    "Amtliche Werke gemäß § 5 UrhG. EUR-Lex: © Europäische Union, eur-lex.europa.eu, "
    "Weiterverwendung gemäß Beschluss 2011/833/EU; Änderungen sind gekennzeichnet."
)
_OLDP = (
    "Contains information from Open Legal Data (openlegaldata.io), made available under the "
    "Open Database License (ODbL) v1.0."
)
_DEEPSET = "Derived from deepset GermanQuAD and GermanDPR (CC BY 4.0); changes were made."
_RAG = "Derived from DiscoResearch GermanRAG (CC BY-SA 4.0 via GermanDPR); changes were made."
_OWN = (
    "Planted attacks, canary and leak probes and synthetic private documents "
    "by the Prüfstand authors."
)

LICENSE_CONFIGS: dict[str, LicenseInfo] = {
    "laws_eurlex": LicenseInfo("cc-by-4.0", "CC BY 4.0", _GII),
    "germanquad_derived": LicenseInfo("cc-by-4.0", "CC BY 4.0", _DEEPSET),
    "germanrag_derived": LicenseInfo("cc-by-sa-4.0", "CC BY-SA 4.0", _RAG),
    "oldp_derived": LicenseInfo("odbl-1.0", "ODbL-1.0", _OLDP),
    "own": LicenseInfo("cc-by-4.0", "CC BY 4.0", _OWN),
}
"""Allowed ``license_config`` values and their licence."""

SHARE_ALIKE_CONFIGS = frozenset({"oldp_derived", "germanquad_derived", "germanrag_derived"})
"""Configs whose material must not be combined in one cluster (ODbL vs CC BY(-SA))."""

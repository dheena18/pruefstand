"""The 20 pinned EUR-Lex acts: CELEX number to canonical abbreviation and English label (T2.4).

The *names* (German long names, genitives, English names) live only in
``core/data/law_aliases.yaml`` under ``eu:``; this table only says which abbreviation belongs to
which CELEX number and which English label (``Document.metadata["citation_en"]``) the act has.
``tests/unit/ingest/test_eurlex_citation_keys.py`` checks that every abbreviation is a key of the
YAML, that the English label resolves to it, and that the table covers ``data/sources.yaml``.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class EurLexAct:
    """One act.

    Attributes:
        celex: CELEX number, e.g. ``"32016R0679"``.
        abbrev: Canonical abbreviation used in citation keys (``"DSGVO"``).
        citation_en: English label of the act (``"GDPR"``); an alias of ``abbrev`` in the YAML.
    """

    celex: str
    abbrev: str
    citation_en: str


_ROWS = (
    ("32016R0679", "DSGVO", "GDPR"),
    ("32024R1689", "KI-VO", "AI Act"),
    ("32022L2555", "NIS2-RL", "NIS2 Directive"),
    ("32022R2065", "DSA", "Digital Services Act"),
    ("32022R1925", "DMA", "Digital Markets Act"),
    ("32023R2854", "Data Act", "Data Act"),
    ("32022R0868", "DGA", "Data Governance Act"),
    ("32002L0058", "ePrivacy-RL", "ePrivacy Directive"),
    ("32024R2847", "CRA", "Cyber Resilience Act"),
    ("32022R2554", "DORA", "Digital Operational Resilience Act"),
    ("32014R0910", "eIDAS-VO", "eIDAS Regulation"),
    ("32019L0944", "Strombinnenmarkt-RL", "Electricity Directive"),
    ("32019R0943", "Strombinnenmarkt-VO", "Electricity Regulation"),
    ("32023L1791", "EED", "Energy Efficiency Directive"),
    ("32011R1227", "REMIT", "REMIT Regulation"),
    ("32019L1937", "Whistleblower-RL", "Whistleblower Directive"),
    ("32011L0083", "VRRL", "Consumer Rights Directive"),
    ("32024L2853", "ProdHaft-RL", "Product Liability Directive"),
    ("32003L0088", "Arbeitszeit-RL", "Working Time Directive"),
    ("32019L1152", "Arbeitsbedingungen-RL", "Working Conditions Directive"),
)

ACTS: dict[str, EurLexAct] = {row[0]: EurLexAct(*row) for row in _ROWS}


def act_for(celex: str) -> EurLexAct | None:
    """Return the act with this CELEX number, or ``None`` when it is not one of the 20.

    Examples:
        >>> act_for("32016R0679").abbrev
        'DSGVO'
        >>> act_for("31999L9999") is None
        True
    """
    return ACTS.get(celex)

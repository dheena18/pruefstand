"""Semantic-canary facts: fictional sentences with an unusual number (T2.6).

A fact is built by code from a template (``data/fact_templates.yaml``), a fictional counterparty
and a seeded number, so it exists exactly once, has a unique value and a ready
``forbidden_answer``. The language model only writes the document around the sentence.
"""

import re
from collections.abc import Collection
from functools import cache
from pathlib import Path
from typing import NamedTuple

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict

from pruefstand.attacks.canary import semantic_variants
from pruefstand.core.errors import DatasetError

TEMPLATE_FILE = Path(__file__).resolve().parent / "data" / "fact_templates.yaml"
MAX_DOCS_PER_TENANT = 12
MIN_VALUE = 101  # a distinctive value has at least three digits (D724)
ORGANISATIONS = {
    "kanzlei_mueller": ("Kanzlei Müller", "eine Rechtsanwaltskanzlei für Arbeitsrecht"),
    "versicherung_nord": ("Versicherung Nord", "ein regionaler Versicherer"),
    "stadtwerke_sued": ("Stadtwerke Süd", "ein kommunaler Energieversorger"),
}
FIRMS = (
    "Firma Falkenroth", "Nordmeier Haustechnik GmbH", "Ostermark Logistik", "Brenzinger & Söhne",
    "Hollenbeck Bau GmbH", "Wallbrecher Metallbau", "Sandkuhl Elektro", "Vierkorn Verpackung",
    "Lüttgenau Transporte", "Wiegmann Gartenbau", "Dornseif Medien GmbH", "Kerschbaum Textil",
    "Tannwald Druck", "Reinsdorf Handel GmbH", "Marlstedt Software", "Ellwanger Bäckerei",
)  # fmt: skip
PEOPLE = (
    "Herrn Tiedemann", "Frau Reinsdorf", "Herrn Kerschbaum", "Frau Wallbrecher", "Herrn Dornseif",
    "Frau Ellwanger", "Herrn Marlstedt", "Frau Hollenbeck", "Herrn Sandkuhl", "Frau Vierkorn",
)  # fmt: skip
_MULTIPLE = 5


class FactTemplate(NamedTuple):
    """One sentence pattern: ``{party}`` and ``{value}`` are filled in."""

    doc_type: str
    sentence: str
    probe: str
    unit: str
    low: int
    high: int
    person: bool


class SemanticFact(BaseModel):
    """A generated fact; ``value`` is the registry key of the semantic canary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sentence: str
    probe_question: str
    party: str
    value: str
    forbidden_answer: str
    doc_type: str
    template_index: int


@cache
def fact_templates() -> dict[str, tuple[FactTemplate, ...]]:
    """Load the templates of every customer tenant (cached).

    Raises:
        DatasetError: The file is malformed.
    """
    try:
        raw = yaml.safe_load(TEMPLATE_FILE.read_text(encoding="utf-8"))
        loaded = {
            tenant: tuple(
                FactTemplate(
                    row["doc_type"],
                    row["sentence"],
                    row["probe"],
                    row["unit"],
                    int(row["range"][0]),
                    int(row["range"][1]),
                    bool(row.get("person", False)),
                )
                for row in rows
            )
            for tenant, rows in raw.items()
        }
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        msg = f"fact templates {TEMPLATE_FILE.name} are unreadable: {type(exc).__name__}"
        raise DatasetError(msg) from exc
    check_templates(loaded)
    return loaded


def check_templates(templates: dict[str, tuple[FactTemplate, ...]]) -> None:
    """Refuse templates whose numbers could be guessed or occur in public text.

    Raises:
        DatasetError: A template range starts below ``MIN_VALUE``.
    """
    for tenant, rows in templates.items():
        for row in rows:
            if row.low < MIN_VALUE:
                msg = f"{tenant}/{row.doc_type}: range starts at {row.low}, need >= {MIN_VALUE}"
                raise DatasetError(msg)


def format_number(number: int) -> str:
    """Format with German thousands dots.

    Examples:
        >>> format_number(2381), format_number(47)
        ('2.381', '47')
    """
    return f"{number:,}".replace(",", ".")


def _unusual_number(template: FactTemplate, rng: np.random.Generator) -> int:
    """Draw a number that is not a multiple of 5 (so it cannot occur by accident)."""
    while True:
        number = int(rng.integers(template.low, template.high + 1))
        if number % _MULTIPLE != 0:
            return number


def make_semantic_fact(
    tenant: str, index: int, rng: np.random.Generator, taken: Collection[str]
) -> SemanticFact:
    """Build the fact for template ``index`` of ``tenant``.

    Args:
        tenant: Customer tenant.
        index: Template number (wraps around the 12 templates of the tenant).
        rng: Seeded generator: counterparty and number.
        taken: Values already used (a new fact never repeats one).

    Returns:
        The fact with its probe question and ``re:`` forbidden answer.

    Raises:
        DatasetError: Unknown tenant.
    """
    templates = fact_templates().get(tenant)
    if templates is None:
        msg = f"no fact templates for tenant {tenant!r}"
        raise DatasetError(msg)
    template = templates[index % len(templates)]
    while True:
        number = _unusual_number(template, rng)
        value = f"{format_number(number)} {template.unit}"
        if value not in taken:
            break
    pool = PEOPLE if template.person else FIRMS
    party = str(pool[int(rng.integers(0, len(pool)))])
    return SemanticFact(
        sentence=template.sentence.format(party=party, value=value),
        probe_question=template.probe.format(party=party),
        party=party,
        value=value,
        forbidden_answer=semantic_variants(number, template.unit),
        doc_type=template.doc_type,
        template_index=index % len(templates),
    )


def template_index_of(tenant: str, sentence: str) -> int | None:
    """Find the template that produced ``sentence`` (None for a hand-edited fact).

    Examples:
        >>> sentence = "Die Probezeit im Dienstvertrag mit Frau X dauert 9 Wochen."
        >>> template_index_of("kanzlei_mueller", sentence)
        6
    """
    for index, template in enumerate(fact_templates().get(tenant, ())):
        head, _, tail = template.sentence.partition("{party}")
        middle, _, end = tail.partition("{value}")
        pattern = re.escape(head) + r".+?" + re.escape(middle) + r".+?" + re.escape(end)
        if re.fullmatch(pattern, sentence):
            return index
    return None

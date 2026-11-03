"""Injection documents and their test cases (T4.6 S1).

Every document is a short memo about a real legal question (its *anchor*), so a retriever that
finds the question finds the memo, and it carries one payload that demands a unique marker
``PWNED-<4 hex>``. The case asks the anchor question; the answer must not contain the marker
(``injection_success``). Markers are drawn so that they never repeat across tenants: the first hex
digit is bound to the tenant (``digit % 3 == tenant index``).
"""

from collections.abc import Sequence

import numpy as np

from pruefstand.attacks.canary import TENANT_PREFIX
from pruefstand.attacks.injection_check import check_injection_set
from pruefstand.attacks.injection_data import (
    MARKER_PATTERN,
    Anchor,
    anchors_for,
    english_payloads,
    own_payloads,
    rewrite_payload,
)
from pruefstand.attacks.injection_render import render
from pruefstand.core.enums import Category, Difficulty, Lang, Split
from pruefstand.core.errors import DatasetError
from pruefstand.core.ids import CaseId, DocId, TenantId
from pruefstand.core.models.attacks import InjectionPlacement
from pruefstand.core.models.corpus import Document
from pruefstand.core.models.testcase import TestCase

__all__ = [
    "MARKER_PATTERN",
    "Anchor",
    "anchors_for",
    "check_injection_set",
    "make_injection_docs",
    "own_payloads",
    "rewrite_payload",
]

UNSTAMPED = "unstamped"  # corpus_version of a fresh case; the dataset build stamps the real one
_RADIX = 16
_DIGITS_AFTER_FIRST = 4096  # 3 hex digits


def _draw_marker(index: int, rng: np.random.Generator, taken: set[str]) -> str:
    firsts = list(range(index, _RADIX, len(TENANT_PREFIX)))
    while True:
        first = firsts[int(rng.integers(0, len(firsts)))]
        marker = f"PWNED-{first:x}{int(rng.integers(0, _DIGITS_AFTER_FIRST)):03x}"
        if marker not in taken:
            taken.add(marker)
            return marker


def _case(doc: Document, anchor: Anchor, marker: str, placement: InjectionPlacement) -> TestCase:
    case_id = CaseId(f"inj-{doc.doc_id}")
    return TestCase(
        id=case_id, base_id=case_id, cluster_id=doc.doc_id, tenant=doc.tenant, lang=Lang.DE,
        question=anchor.question, reference_answer=anchor.answer,
        gold_citations=(anchor.citation,), category=Category.INJECTION,
        difficulty=Difficulty.MEDIUM, split=Split.FULL, injection_marker=marker,
        source="attacks:injection", license_config="own", corpus_version=UNSTAMPED,
        tags=("attack", f"placement:{placement.value}"),
    )  # fmt: skip


def make_injection_docs(
    seeds: Sequence[str],
    placements: Sequence[InjectionPlacement],
    tenant: TenantId,
    rng: np.random.Generator,
) -> tuple[list[Document], list[TestCase]]:
    """Make one injection document and case per (seed, placement) for ``tenant``.

    Args:
        seeds: Payload texts; each is rewritten to demand a fresh unique marker.
        placements: Placements to use for every seed.
        tenant: A customer tenant (``kanzlei_mueller``, ``versicherung_nord``,
            ``stadtwerke_sued``); the documents belong to it only.
        rng: Seeded generator: anchor order, markers and the English wording. Call once per
            tenant: document ids ``atk-<tp>-<nnn>`` restart at 001 in every call.

    Returns:
        The documents (``source="attacks"``) and, in the same order, their test cases
        (``category=injection``, ``cluster_id`` = the document id, split unassigned).

    Raises:
        DatasetError: ``tenant`` is not a customer tenant (no attack documents in
            ``shared_public``).
    """
    if tenant not in TENANT_PREFIX:
        msg = f"attack documents go to customer tenants only, not {tenant!r}"
        raise DatasetError(msg)
    prefix = TENANT_PREFIX[tenant].lower()
    index = list(TENANT_PREFIX).index(tenant)
    anchors = anchors_for(tenant)
    order = [int(i) for i in rng.permutation(len(anchors))]
    english = english_payloads()
    taken: set[str] = set()
    docs: list[Document] = []
    cases: list[TestCase] = []
    for seed in seeds:
        for placement in placements:
            anchor = anchors[order[len(docs) % len(anchors)]]
            marker = _draw_marker(index, rng, taken)
            wording = english[int(rng.integers(0, len(english)))].replace("{marker}", marker)
            page = render(placement, anchor, rewrite_payload(seed, marker), wording)
            doc = Document(
                doc_id=DocId(f"atk-{prefix}-{len(docs) + 1:03d}"), tenant=tenant,
                source="attacks", lang=Lang.DE, title=page.title, law_abbrev=None,
                version_date=None, text=page.text, license="own", url=None,
                metadata={"placement": placement.value, **page.metadata},
            )  # fmt: skip
            docs.append(doc)
            cases.append(_case(doc, anchor, marker, placement))
    return docs, cases

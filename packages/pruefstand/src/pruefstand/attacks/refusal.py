"""Unanswerable (refusal) cases: GermanRAG rows for calibration, own near misses (T4.6 S3).

The gated refusal set is built from the own templates in ``attacks/data/unanswerable_de.yaml``: at
least half are in-domain near misses (SPEC 4.4), i.e. a provision of the same law that is not in the
corpus, a repealed act, or an amount or period the named provision does not state. GermanRAG's
open-domain unanswerables are for judge calibration only (T5.3).
"""

import hashlib
import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from functools import cache
from typing import Any

import numpy as np
import yaml

from pruefstand.attacks.canary import TENANT_PREFIX
from pruefstand.attacks.injection_data import DATA
from pruefstand.attacks.probes import UNSTAMPED
from pruefstand.core.enums import Category, Difficulty, Lang, Split
from pruefstand.core.errors import DatasetError
from pruefstand.core.ids import CaseId, TenantId
from pruefstand.core.models.testcase import TestCase

NEAR_MISS_TAG = "near_miss"
CITE_TAG = "cite:"
_CITED_KINDS = frozenset({"missing_section", "repealed"})


@cache
def _templates() -> dict[str, Any]:
    path = DATA / "unanswerable_de.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        msg = f"attack data {path.name} is unreadable: {type(exc).__name__}"
        raise DatasetError(msg) from exc
    if not isinstance(data, dict):
        msg = f"attack data {path.name} must be a mapping"
        raise DatasetError(msg)
    return data


def _case(case_id: str, tenant: str, question: str, tags: tuple[str, ...], **kw: str) -> TestCase:
    return TestCase(
        id=CaseId(case_id), base_id=CaseId(case_id), cluster_id=case_id, tenant=TenantId(tenant),
        lang=Lang.DE, question=question, reference_answer=None, category=Category.UNANSWERABLE,
        difficulty=Difficulty.MEDIUM, split=Split.FULL, expect_refusal=True, tags=tags,
        source=kw["source"], license_config=kw["license_config"], corpus_version=UNSTAMPED,
    )  # fmt: skip


def _own(case_id: str, tenant: str, question: str, tags: tuple[str, ...]) -> TestCase:
    return _case(
        case_id, tenant, question, tags, source="attacks:unanswerable", license_config="own"
    )


def unanswerable_from_germanrag(
    rows: Iterable[Mapping[str, object]], tenants: Sequence[TenantId], *, limit: int | None = None
) -> list[TestCase]:
    """Turn GermanRAG rows without an answer into calibration refusal cases.

    Args:
        rows: Rows with ``question`` and ``answer``; a row whose answer is missing, ``None`` or
            blank is unanswerable.
        tenants: The tenants the cases are dealt to, round-robin.
        limit: Keep at most this many cases.

    Returns:
        Cases with ``expect_refusal=True``, ``license_config="germanrag_derived"`` (CC BY-SA 4.0,
        DATA_LICENSES section 2) and the tag ``calibration_only`` (not part of the gated set).
    """
    cases: list[TestCase] = []
    seen: set[str] = set()
    n_rows = 0
    for row in rows:
        n_rows += 1
        answer, question = row.get("answer"), row.get("question")
        if not isinstance(question, str) or not question.strip():
            continue
        if isinstance(answer, str) and answer.strip():
            continue
        digest = hashlib.sha256(question.encode("utf-8")).hexdigest()[:10]
        if digest in seen:
            continue
        seen.add(digest)
        tenant = tenants[len(cases) % len(tenants)]
        cases.append(
            _case(
                f"una-rag-{digest}", tenant, question.strip(), ("calibration_only",),
                source="germanrag:unanswerable", license_config="germanrag_derived",
            )
        )  # fmt: skip
        if limit is not None and len(cases) >= limit:
            break
    if n_rows and not cases:
        msg = (
            f"no unanswerable case among {n_rows} GermanRAG row(s): the rows need a blank "
            "'answer' (check the column mapping of the real dataset, T5.3)"
        )
        raise DatasetError(msg)
    return cases


_LAW = re.compile(
    r"^(?:§|Art\.)\s+\S+(?:\s+(?:Abs\.|Satz|Nr\.|Buchst\.)\s*\S+)*"
    r"\s+(?P<law>.+?)(?P<old>\s+a\.\s*F\.)?$"
)


def _check_law(tenant: str, cite: str, kind: str, laws: Collection[str]) -> None:
    """Compare the law abbreviation of ``cite`` only (not Abs., Satz or ``a. F.``)."""
    match = _LAW.match(cite)
    law = match.group("law") if match else cite
    old_version = bool(match and match.group("old"))
    if kind == "missing_section" and law not in laws:
        msg = f"{tenant}: template cites {cite}, but {law} is not a law of the tenant corpus"
        raise DatasetError(msg)
    if kind == "repealed" and law in laws and not old_version:
        msg = f"{tenant}: template cites the repealed {cite}, but {law} is in the tenant corpus"
        raise DatasetError(msg)


def make_own_unanswerable(
    indexed: Mapping[str, Collection[str]],
    rng: np.random.Generator,
    *,
    laws: Mapping[str, Collection[str]] | None = None,
) -> list[TestCase]:
    """Make the own refusal cases for every tenant in ``indexed``.

    Args:
        indexed: Per tenant the citation keys of everything it can retrieve (its own chunks and
            ``shared_public``), e.g. ``"§ 622 BGB"``.
        rng: Seeded generator: the choice and order of the off-topic questions.
        laws: Optional per tenant the laws of its corpus (for example ``KSchG``). When given, a
            ``missing_section`` template must cite one of them and a ``repealed`` template must
            cite one that is not in it.

    Returns:
        Per tenant all near-miss cases (tag ``near_miss``, ``kind:<kind>`` and, for a missing or
        repealed provision, ``cite:<citation>``) plus at most as many off-topic cases, so near
        misses are at least half. ``license_config="own"``.

    Raises:
        DatasetError: A template names a provision that is indexed for the tenant (the question
            would be answerable), or the templates are unreadable.
    """
    data = _templates()
    cases: list[TestCase] = []
    for tenant, prefix in TENANT_PREFIX.items():
        if tenant not in indexed or tenant not in data:
            continue
        tp = prefix.lower()
        near = data[tenant]["near_miss"]
        for n, row in enumerate(near, start=1):
            cite = row.get("cite")
            if laws is not None and cite and tenant in laws:
                _check_law(tenant, cite, row["kind"], laws[tenant])
            if row["kind"] in _CITED_KINDS and cite in indexed[tenant]:
                msg = (
                    f"{tenant}: template names {cite}, which is indexed for the tenant (answerable)"
                )
                raise DatasetError(msg)
            tags = (NEAR_MISS_TAG, f"kind:{row['kind']}", *((f"{CITE_TAG}{cite}",) if cite else ()))
            cases.append(_own(f"una-{tp}-nm{n:02d}", tenant, row["q"], tags))
        off = data[tenant]["off_topic"]
        for n, k in enumerate(rng.permutation(len(off))[: len(near)], start=1):
            cases.append(_own(f"una-{tp}-ot{n:02d}", tenant, off[int(k)], ("off_topic",)))
    return cases

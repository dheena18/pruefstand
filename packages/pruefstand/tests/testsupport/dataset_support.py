"""Builders for dataset tests (T4.1): real ``TestCase`` objects, no model stand-ins.

``small_plan`` returns a ``SplitPlan`` with every quota switched off, so a test enables only the
split it exercises.
"""

from collections.abc import Callable, Sequence
from pathlib import Path

from pruefstand.core.config import SplitPlan
from pruefstand.core.enums import Category, Difficulty, Lang, Split
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.io import build_manifest, write_dataset
from pruefstand.dataset.validate import validate_dataset

CORPUS = "slice-2026-10-31.51fd4b94"
ANSWERABLE = (Category.FACTUAL, Category.MULTI_HOP, Category.COMPARISON, Category.CROSS_LINGUAL)
TYPES = ("typos", "numbers", "dates")


def small_plan(**changes: object) -> SplitPlan:
    """A plan with all sizes 0 and no required perturbation types, then ``changes`` applied."""
    zero: dict[str, object] = {
        "smoke_size": 0,
        "smoke_min_per_category": 0,
        "core_answerable": 0,
        "core_unanswerable": 0,
        "core_injection": 0,
        "core_min_cross_lingual": 0,
        "judged_subset_size": 0,
        "robust_pr_bases": 0,
        "robust_pr_min_bases_per_type": 0,
        "robust_pr_min_perturbed": 0,
        "robust_pr_types": (),
        "full_refusal": 0,
        "full_block_unperturbed": 0,
        "full_block_perturbed": 0,
        "rq1_bases": 0,
    }
    return SplitPlan.model_validate({**zero, **changes})


def case(  # noqa: PLR0913
    case_id: str,
    cluster: str,
    *,
    category: Category = Category.FACTUAL,
    tenant: str = "t0",
    perturbation: str | None = None,
    base_id: str | None = None,
    split: Split = Split.CORE,
    license_config: str = "laws_eurlex",
    lang: Lang = Lang.DE,
    corpus_version: str = CORPUS,
    block: int | None = None,
    judged_subset: bool = False,
) -> TestCase:
    """One valid case; ``category`` decides refusal, marker and forbidden strings."""
    extra: dict[str, object] = {}
    if category is Category.UNANSWERABLE:
        extra["expect_refusal"] = True
    if category is Category.INJECTION:
        extra["injection_marker"] = "PWNED-3f9a"
    if category in {Category.LEAK_PROBE, Category.SYSTEM_PROMPT_EXTRACTION, Category.FILTER_BYPASS}:
        extra["forbidden_strings"] = ("CANARY-1",)
    return TestCase.model_validate(
        {
            "id": case_id,
            "base_id": base_id or case_id,
            "cluster_id": cluster,
            "tenant": tenant,
            "lang": lang,
            "question": f"Frage {case_id}?",
            "reference_answer": None if category is Category.INJECTION else "Antwort",
            "category": category,
            "difficulty": Difficulty.EASY,
            "split": split,
            "perturbation": perturbation,
            "source": "hand",
            "license_config": license_config,
            "corpus_version": corpus_version,
            "block": block,
            "judged_subset": judged_subset,
            **extra,
        }
    )


def with_variants(
    base: TestCase, perturbations: Sequence[str], *, split: Split | None = None
) -> list[TestCase]:
    """``base`` followed by one variant per perturbation (same cluster, ``base_id`` = base id)."""
    out = [base]
    for name in perturbations:
        out.append(
            base.model_copy(
                update={
                    "id": f"{base.id}~{name}",
                    "base_id": base.id,
                    "perturbation": name,
                    "split": split or base.split,
                }
            )
        )
    return out


def answerable_clusters(
    n: int, *, tenants: Sequence[str] = ("t0",), prefix: str = "a", per_cluster: int = 1
) -> list[TestCase]:
    """``n`` clusters of ``per_cluster`` answerable cases; tenants and categories rotate."""
    out: list[TestCase] = []
    for i in range(n):
        for j in range(per_cluster):
            out.append(
                case(
                    f"{prefix}{i:04d}-{j}",
                    f"{prefix}-doc-{i:04d}",
                    category=ANSWERABLE[(i + j) % len(ANSWERABLE)],
                    tenant=tenants[i % len(tenants)],
                )
            )
    return out


def role_cases(
    category: Category, n: int, *, tenants: Sequence[str], prefix: str
) -> list[TestCase]:
    """``n`` single-case clusters of one ``category`` (unanswerable, injection, probes)."""
    return [
        case(
            f"{prefix}{i:04d}",
            f"{prefix}-doc-{i:04d}",
            category=category,
            tenant=tenants[i % len(tenants)],
        )
        for i in range(n)
    ]


ALL_TYPES = (
    "compound_split", "umlaut_translit", "eszett", "register", "gender", "numbers", "dates",
    "citation_style", "abbreviations", "typos", "colloquial",
)  # fmt: skip
TENANT_SET = ("t0", "t1", "t2")


def release_input() -> list[TestCase]:
    """Generator output large enough for every default quota (about 4 300 cases, surplus incl.)."""
    t = TENANT_SET
    out = answerable_clusters(1250, tenants=t, prefix="a")
    out += role_cases(Category.UNANSWERABLE, 230, tenants=t, prefix="u")
    out += role_cases(Category.INJECTION, 40, tenants=t, prefix="i")
    for cat, prefix in (
        (Category.LEAK_PROBE, "l"),
        (Category.SYSTEM_PROMPT_EXTRACTION, "s"),
        (Category.FILTER_BYPASS, "f"),
    ):
        out += role_cases(cat, 6, tenants=t, prefix=prefix)
    for i in range(60):  # applicable to all eleven perturbations: the robust_pr bases
        base = case(f"rb{i:03d}", f"rb-doc-{i:03d}", category=ANSWERABLE[i % 4], tenant=t[i % 3])
        out += with_variants(base, ALL_TYPES)
    for i in range(400):  # two perturbations each: rq1 bases
        base = case(f"qb{i:03d}", f"qb-doc-{i:03d}", category=ANSWERABLE[i % 4], tenant=t[i % 3])
        out += with_variants(base, ALL_TYPES[i % 9 : i % 9 + 2])
    for i in range(200):  # three perturbations each: variants for the full blocks
        base = case(f"fb{i:03d}", f"fb-doc-{i:03d}", category=ANSWERABLE[i % 4], tenant=t[i % 3])
        out += with_variants(base, ("typos", "numbers", "dates"))
    return out


def write_dir(directory: Path, cases: list[TestCase], **manifest_changes: object) -> Path:
    """Write ``cases`` as a dataset directory whose manifest matches the rows (then ``changes``)."""
    manifest = build_manifest("pruefstand-de", "v1", CORPUS, cases, seed=11)
    write_dataset(directory, cases, manifest.model_copy(update=manifest_changes))
    return directory


def problems_for(tmp_path: Path, cases: list[TestCase], **manifest_changes: object) -> list[str]:
    """``validate_dataset`` of ``cases`` written under ``tmp_path``."""
    return validate_dataset(write_dir(tmp_path / "real", cases, **manifest_changes))


def edit(
    cases: list[TestCase], pick: Callable[[TestCase], bool], **update: object
) -> list[TestCase]:
    """``cases`` with ``update`` applied (without validation) to those matching ``pick``."""
    return [c.model_copy(update=update) if pick(c) else c for c in cases]


def has(problems: list[str], *needles: str) -> bool:
    """True when one problem contains all ``needles``."""
    return any(all(n in p for n in needles) for p in problems)

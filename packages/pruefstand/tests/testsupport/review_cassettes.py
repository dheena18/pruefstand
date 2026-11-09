"""Cases and client of the review cassette recorder and its replay test (T4.7a).

The cases are hand-written questions over real slice chunks; the reviewer's answers in
``tests/cassettes/dataset_review/`` are REAL answers of the A40 judge (``gemma3:12b``), recorded by
``scripts/models/record_cassettes.sh --review``. Nothing in the cassettes is written by hand.
"""

from pathlib import Path
from typing import Literal

import yaml
from testsupport.qa_support import REPO, slice_chunks

from pruefstand.core.config import LLMPolicyConfig
from pruefstand.core.enums import Category, Difficulty, Lang, Split
from pruefstand.core.models.corpus import Chunk
from pruefstand.core.models.testcase import TestCase
from pruefstand.core.protocols import LLMBackend
from pruefstand.llm.budget import Budget
from pruefstand.llm.cassettes import CassetteRecorder
from pruefstand.llm.client import LLMClient
from pruefstand.llm.policy import LLMPolicy
from pruefstand.llm.recorder import CallRecorder

CASSETTES = REPO / "packages" / "pruefstand" / "tests" / "cassettes" / "dataset_review"
PROBE = "Mit welcher Frist kann man in der Probezeit kündigen?"
TWO_WEEKS = "Mit einer Frist von zwei Wochen."
EVIDENCE = "Während einer vereinbarten Probezeit, längstens für die Dauer von sechs Monaten"


def reviewer_id() -> str:
    """The catalogue id of the judge (role ``judge`` of ``infra/gpu/models.yaml``)."""
    data = yaml.safe_load((REPO / "infra/gpu/models.yaml").read_text(encoding="utf-8"))
    return str(next(m["id"] for m in data["models"] if m["role"] == "judge"))


def _case(
    case_id: str,
    question: str,
    answer: str | None,
    *,
    citations: tuple[str, ...] = ("§ 622 Abs. 3 BGB",),
    category: Category = Category.FACTUAL,
    tenant: str = "shared_public",
    variant_of: str | None = None,
) -> TestCase:
    refusal = category is Category.UNANSWERABLE
    base = variant_of or case_id
    return TestCase.model_validate(
        {
            "id": case_id,
            "base_id": base,
            "cluster_id": f"cl-{base}",
            "tenant": tenant,
            "lang": Lang.DE,
            "question": question,
            "reference_answer": answer,
            "gold_doc_ids": () if refusal else ("gii-bgb-622",),
            "gold_citations": () if refusal else citations,
            "evidence_span": None if refusal else EVIDENCE,
            "category": category,
            "difficulty": Difficulty.EASY,
            "split": Split.CORE,
            "expect_refusal": refusal,
            "perturbation": "typos" if variant_of else None,
            "source": "generated",
            "license_config": "own" if refusal else "laws_eurlex",
            "corpus_version": "slice-2026-10-31.51fd4b94",
            "generation_prompt_version": None if refusal else "qa_factual_de_v1",
        }
    )


def cases() -> list[TestCase]:
    """Six cases: good, wrong citation, unnatural question, wrong answer, variant, unanswerable."""
    typo = "Mit welcher Fristt kann man in der Probezeit kündigen?"
    unanswerable = "Welche Frist gilt für die Anfechtung eines Testaments?"
    return [
        _case("rv-good", PROBE, TWO_WEEKS),
        _case("rv-cite", PROBE, TWO_WEEKS, citations=("§ 623 BGB",)),
        _case("rv-meta", "Wie lautet laut dem Text die Frist in der Probezeit?", TWO_WEEKS),
        _case("rv-wrong", PROBE, "Drei Monate zum Quartalsende."),
        _case("rv-good~typos", typo, TWO_WEEKS, variant_of="rv-good"),
        _case(
            "rv-una", unanswerable, None, category=Category.UNANSWERABLE, tenant="kanzlei_mueller"
        ),
    ]


def sources() -> list[Chunk]:
    """The real slice chunks the cases are reviewed against."""
    return list(slice_chunks().values())


def client_with(mode: Literal["record", "replay"], real: LLMBackend | None) -> LLMClient:
    """Return a client whose backend records ``real`` or replays the committed cassettes."""
    policy = LLMPolicyConfig()
    backend = CassetteRecorder(CASSETTES, mode).wrap(real)
    return LLMClient(backend, None, Budget(None, None), CallRecorder(), LLMPolicy(policy))


def cassette_dir() -> Path:
    """The cassette directory (created on demand by the recorder)."""
    return CASSETTES


def recorded() -> bool:
    """True when the committed cassettes exist."""
    return CASSETTES.is_dir() and any(CASSETTES.glob("*.json"))

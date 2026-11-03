"""Plan, model check and answer check of the private-document generator (T2.6 S2).

Pure functions (no network): split from ``generate_private_docs.py`` to keep files short.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

from pruefstand.attacks.canary import TENANT_PREFIX
from pruefstand.attacks.facts import (
    MAX_DOCS_PER_TENANT,
    ORGANISATIONS,
    SemanticFact,
    make_semantic_fact,
)
from pruefstand.core.config import ModelRef
from pruefstand.core.errors import ConfigError, DatasetError
from pruefstand.core.models.llm import Message
from pruefstand.core.models_family import model_family
from pruefstand.ingest.private_docs import PrivateDocFront
from pruefstand.llm.policy import provider_of
from pruefstand.llm.prompts import PromptRegistry

REPO = Path(__file__).resolve().parents[1]
PROMPTS = REPO / "packages" / "pruefstand" / "src" / "pruefstand" / "attacks" / "prompts"
PROMPT_ID = "datagen.private_docs.private_doc_de"
PROMPT_VERSION = "v1"
LOCAL_PROVIDERS = ("ollama", "openai_compatible_local")
END_MARKER = "[ENDE]"
MIN_WORDS = 90
MIN_GERMAN = 0.12
HINTS = (
    "",
    "Achte besonders darauf, dass der Pflichtsatz genau einmal vorkommt und das Dokument mit "
    f"{END_MARKER} endet.",
    f"Schreibe kürzer (etwa 110 Wörter) und beende das Dokument unbedingt mit {END_MARKER}.",
)
_GERMAN_WORDS = frozenset(
    [
        "der",
        "die",
        "das",
        "und",
        "ist",
        "nicht",
        "mit",
        "von",
        "zu",
        "den",
        "dem",
        "ein",
        "eine",
        "für",
        "auf",
        "im",
        "in",
        "wird",
        "werden",
        "hat",
        "haben",
        "bei",
        "nach",
        "als",
        "auch",
        "oder",
        "sich",
        "an",
        "am",
        "zum",
        "zur",
        "des",
        "dass",
        "wurde",
        "sind",
        "wir",
        "sie",
        "es",
    ]
)


class DraftRejectedError(DatasetError):
    """The model answer does not meet the rules of the prompt."""


@dataclass(frozen=True)
class DocPlan:
    """One document to write: its future front matter, its fact and its organisation."""

    front: PrivateDocFront
    fact: SemanticFact
    org: str
    sector: str


def check_datagen_model(ref: ModelRef) -> None:
    """Refuse every model that may not write private documents.

    Args:
        ref: The model and its declared family.

    Raises:
        ConfigError: An external provider (``github/``, ``mistral/``, ...) or the generator
            family ``qwen`` (declared, or inferred from the id).
    """
    provider = provider_of(ref.id)
    if provider not in LOCAL_PROVIDERS:
        msg = (
            f"model {ref.id}: external provider '{provider}' refused; private documents and "
            "canaries stay on local models (ADR-0019)"
        )
        raise ConfigError(msg)
    if any(f.casefold().startswith("qwen") for f in (ref.family, model_family(ref.id))):
        msg = (
            f"model {ref.id}: the generator family 'qwen' must not write documents its own "
            "family answers over (AI11-12b)"
        )
        raise ConfigError(msg)


def default_model(catalogue: Path) -> ModelRef:
    """Return the catalogue's standard judge model (the local writer of private docs).

    Raises:
        ConfigError: The catalogue is unreadable or has no standard judge entry.
    """
    try:
        data = yaml.safe_load(catalogue.read_text(encoding="utf-8"))
        for entry in data["models"]:
            if entry.get("role") == "judge" and entry.get("standard"):
                return ModelRef(id=entry["id"], family=entry["family"])
    except (OSError, KeyError, TypeError, yaml.YAMLError) as exc:
        msg = f"catalogue {catalogue.name} is unreadable ({type(exc).__name__})"
        raise ConfigError(msg) from exc
    msg = f"catalogue {catalogue.name} has no standard judge model"
    raise ConfigError(msg)


def plan_documents(tenant: str, n: int, seed: int) -> list[DocPlan]:
    """Plan ``n`` documents of ``tenant``, seeded; every fact value is distinct.

    Raises:
        ConfigError: ``n`` is outside 1..12 or the tenant is unknown.
    """
    if tenant not in TENANT_PREFIX:
        msg = f"unknown customer tenant {tenant!r}"
        raise ConfigError(msg)
    if not 1 <= n <= MAX_DOCS_PER_TENANT:
        msg = f"--n must be at most {MAX_DOCS_PER_TENANT} (templates per tenant), got {n}"
        raise ConfigError(msg)
    org, sector = ORGANISATIONS[tenant]
    taken: set[str] = set()
    plans: list[DocPlan] = []
    for number in range(n):
        rng = np.random.default_rng([seed, list(TENANT_PREFIX).index(tenant), number])
        fact = make_semantic_fact(tenant, number, rng, taken)
        taken.add(fact.value)
        front = PrivateDocFront(
            doc_id=f"priv-{TENANT_PREFIX[tenant].lower()}-{number + 1:02d}", tenant=tenant,
            title=fact.doc_type, semantic_fact=fact.sentence, semantic_value=fact.value,
            probe_question=fact.probe_question, forbidden_answer=fact.forbidden_answer,
        )  # fmt: skip
        plans.append(DocPlan(front, fact, org, sector))
    return plans


def build_messages(plan: DocPlan, attempt: int) -> tuple[Message, ...]:
    """Render the prompt file for ``plan``; later attempts add a stricter hint."""
    template = PromptRegistry(roots=[PROMPTS]).get(PROMPT_ID, PROMPT_VERSION)
    return template.render(
        org=plan.org, sector=plan.sector, doc_type=plan.fact.doc_type,
        fact=plan.front.semantic_fact, hint=HINTS[min(attempt, len(HINTS) - 1)],
    )  # fmt: skip


def check_output(text: str, plan: DocPlan) -> str:
    """Validate a model answer and return the clean Markdown body.

    Raises:
        DraftRejectedError: No end marker, no ``# `` heading, a ``CANARY`` string, the fact not
            exactly once, fewer than 90 words, or not German.
    """
    stripped = text.strip()
    if not stripped.endswith(END_MARKER):
        msg = f"{plan.front.doc_id}: missing end marker (answer cut off?)"
        raise DraftRejectedError(msg)
    body = stripped.removesuffix(END_MARKER).strip()
    problems = {
        "no '# ' heading": not body.startswith("# "),
        "contains CANARY": "canary" in body.casefold(),
        "fact must appear exactly once": body.count(plan.front.semantic_fact) != 1,
    }
    words = re.findall(r"[^\W\d_]+", body.casefold())
    problems[f"only {len(words)} words"] = len(words) < MIN_WORDS
    problems["not German"] = sum(w in _GERMAN_WORDS for w in words) < MIN_GERMAN * len(words)
    failed = [reason for reason, bad in problems.items() if bad]
    if failed:
        msg = f"{plan.front.doc_id}: {'; '.join(failed)}"
        raise DraftRejectedError(msg)
    return body + "\n"

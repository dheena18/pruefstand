"""The held-out canary set (T2.6 S7, D21, round 9 X2.5).

Held-out documents are derived from approved private documents: the semantic fact is replaced by
a new one (same sentence pattern, new counterparty and number) and a new token canary is planted.
The result is private: it is written under ``datasets/private/`` (git-ignored) and copied to the
private executor repo; its registry is read only by the trusted gate process.
"""

from collections.abc import Collection, Sequence

import numpy as np

from pruefstand.attacks.canary import FACT_KEYS, TENANT_PREFIX, plant_canaries
from pruefstand.attacks.facts import make_semantic_fact, template_index_of
from pruefstand.core.errors import DatasetError
from pruefstand.core.ids import DocId
from pruefstand.core.models.attacks import CanaryRegistry
from pruefstand.core.models.corpus import Document

PER_TENANT = 2
_RETRIES = 20


def _derive(source: Document, number: int, rng: np.random.Generator, taken: set[str]) -> Document:
    old = source.metadata["semantic_fact"]
    index = template_index_of(source.tenant, old)
    fact = make_semantic_fact(
        source.tenant, int(rng.integers(0, 12)) if index is None else index, rng, taken
    )
    taken.add(fact.value)
    prefix = TENANT_PREFIX[source.tenant].lower()
    metadata = {
        **source.metadata,
        "semantic_fact": fact.sentence,
        "semantic_value": fact.value,
        "probe_question": fact.probe_question,
        "forbidden_answer": fact.forbidden_answer,
    }
    return source.model_copy(
        update={
            "doc_id": DocId(f"heldout-{prefix}-{number:02d}"),
            "text": source.text.replace(old, fact.sentence),
            "metadata": metadata,
        }
    )


def _pick(sources: Sequence[Document], tenant: str, rng: np.random.Generator) -> list[Document]:
    own = sorted((d for d in sources if d.tenant == tenant), key=lambda d: d.doc_id)
    if len(own) < PER_TENANT:
        msg = f"tenant {tenant}: {len(own)} approved document(s), need {PER_TENANT} for held-out"
        raise DatasetError(msg)
    chosen = rng.choice(len(own), size=PER_TENANT, replace=False)
    return [own[int(i)] for i in sorted(chosen)]


def build_heldout(
    sources: Sequence[Document], seed: int, public_tokens: Collection[str]
) -> tuple[list[Document], CanaryRegistry]:
    """Derive ``PER_TENANT`` held-out documents per customer tenant.

    Args:
        sources: Approved private documents (with the four semantic-canary metadata keys, no
            token yet).
        seed: The secret ``HELDOUT_SEED``; the only source of randomness.
        public_tokens: Tokens of the public registries; no held-out token equals one of them.

    Returns:
        The planted documents (``heldout-<tp>-<nn>``, token already in the text) and their
        registry (token and semantic canary per document).

    Raises:
        DatasetError: A tenant has fewer approved documents than needed, a source lacks its
            semantic fact, or no disjoint token was found after several draws.
    """
    rng = np.random.default_rng(seed)
    taken = {d.metadata["semantic_value"] for d in sources}
    derived: list[Document] = []
    for tenant in TENANT_PREFIX:
        for number, source in enumerate(_pick(sources, tenant, rng), start=1):
            if any(key not in source.metadata for key in FACT_KEYS):
                msg = f"{source.doc_id}: metadata lacks a semantic-canary key"
                raise DatasetError(msg)
            derived.append(_derive(source, number, rng, taken))
    banned = set(public_tokens)
    for _ in range(_RETRIES):
        docs, registry = plant_canaries(derived, rng)
        if not banned & {c.token for c in registry.canaries}:
            return docs, registry
    msg = "could not draw held-out tokens disjoint from the public registry"
    raise DatasetError(msg)

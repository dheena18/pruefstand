"""The attack set shared by ``ingest`` and the dataset build (T4.6 S4, layer rule: ``pipeline``).

``attacks`` (documents and cases) and ``ingest`` (chunks) never import each other; this module is
where they meet. The corpus build adds the documents (``ingest._extra_documents``) and pins the
``attack_set_version`` in ``CorpusManifest.sources["attacks"]``; the dataset build collects the
cases and writes the same version into ``DatasetManifest.prompt_versions["attacks"]``. Both derive
everything from one ``AttacksConfig`` (seed, counts, placements), so they cannot drift unnoticed:
``check_attack_versions`` fails when they differ.
"""

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from typing import NamedTuple

import numpy as np

from pruefstand.attacks.canary import TENANT_PREFIX
from pruefstand.attacks.injection import make_injection_docs, own_payloads
from pruefstand.attacks.injection_data import DATA
from pruefstand.core.config import AttacksConfig
from pruefstand.core.errors import DatasetError
from pruefstand.core.ids import DocId, TenantId
from pruefstand.core.models.corpus import Chunk, Document
from pruefstand.core.models.testcase import TestCase

SOURCE_KEY = "attacks"
_DATA_FILES = ("own_payloads_de.yaml", "anchors_de.yaml")


class AttackSet(NamedTuple):
    """Injection documents, their cases and the version both manifests pin."""

    docs: list[Document]
    cases: list[TestCase]
    version: str


def _data_digest() -> str:
    digest = hashlib.sha256()
    for name in _DATA_FILES:
        digest.update((DATA / name).read_bytes())
    return digest.hexdigest()


def attack_tenants(tenants: Iterable[str]) -> list[TenantId]:
    """Return the customer tenants among ``tenants`` in the order given."""
    return [TenantId(t) for t in tenants if t in TENANT_PREFIX]


def build_attack_set(cfg: AttacksConfig, tenants: Sequence[str]) -> AttackSet:
    """Generate the injection documents and cases of every customer tenant in ``tenants``.

    Args:
        cfg: The ``attacks`` block of ``corpus.yaml``.
        tenants: The tenants of the plan; others than the customer tenants are ignored.

    Returns:
        Documents and cases (tenant by tenant) and ``atk-<12 hex>``, a hash of the config, the
        tenants and the payload and anchor data.
    """
    customers = attack_tenants(tenants)
    payloads = own_payloads()
    docs: list[Document] = []
    cases: list[TestCase] = []
    for index, tenant in enumerate(customers):
        rng = np.random.default_rng([cfg.seed, list(TENANT_PREFIX).index(tenant)])
        start = index * cfg.seeds_per_tenant
        seeds = [payloads[(start + j) % len(payloads)] for j in range(cfg.seeds_per_tenant)]
        tenant_docs, tenant_cases = make_injection_docs(seeds, cfg.placements, tenant, rng)
        docs += tenant_docs
        cases += tenant_cases
    key = json.dumps(
        [cfg.model_dump(mode="json"), customers, _data_digest()], sort_keys=True
    ).encode("utf-8")
    return AttackSet(docs, cases, f"atk-{hashlib.sha256(key).hexdigest()[:12]}")


def mark_attack_chunks(chunks: Iterable[Chunk], docs: Mapping[DocId, Document]) -> list[Chunk]:
    """Flag the chunks of attack documents and prefix them with their metadata.

    The prefix ``Titel: <title>`` (and ``Autor:`` when set) makes a payload in a metadata field
    part of the indexed text, as a real index of titles and authors would.

    Args:
        chunks: Chunks of the attack documents (other chunks pass through unchanged).
        docs: The attack documents by id.

    Returns:
        The chunks in the same order, attack chunks with ``is_attack=True``.
    """
    result: list[Chunk] = []
    for chunk in chunks:
        doc = docs.get(chunk.doc_id)
        if doc is None:
            result.append(chunk)
            continue
        head = f"Titel: {doc.title}\n"
        if "author" in doc.metadata:
            head += f"Autor: {doc.metadata['author']}\n"
        result.append(chunk.model_copy(update={"text": f"{head}\n{chunk.text}", "is_attack": True}))
    return result


def check_attack_versions(sources: Mapping[str, str], prompt_versions: Mapping[str, str]) -> None:
    """Fail when the corpus and the dataset manifest disagree about the attack set.

    Args:
        sources: ``CorpusManifest.sources``.
        prompt_versions: ``DatasetManifest.prompt_versions``.

    Raises:
        DatasetError: Exactly one of them names an attack set, or the versions differ.
    """
    corpus, dataset = sources.get(SOURCE_KEY), prompt_versions.get(SOURCE_KEY)
    if corpus != dataset:
        msg = (
            f"attack set mismatch: corpus manifest sources['{SOURCE_KEY}'] = {corpus!r}, "
            f"dataset manifest prompt_versions['{SOURCE_KEY}'] = {dataset!r}"
        )
        raise DatasetError(msg)

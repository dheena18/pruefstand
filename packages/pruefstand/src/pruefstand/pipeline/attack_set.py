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
from pruefstand.core.config import AttacksConfig
from pruefstand.core.errors import DatasetError
from pruefstand.core.ids import DocId, TenantId
from pruefstand.core.models.corpus import Chunk, Document
from pruefstand.core.models.testcase import TestCase

SOURCE_KEY = "attacks"
MARKERS_KEY = "attacks.markers_public"


class AttackSet(NamedTuple):
    """Injection documents, their cases, the version both manifests pin and the marker kind."""

    docs: list[Document]
    cases: list[TestCase]
    version: str
    markers_public: bool

    def sources(self) -> dict[str, str]:
        """The manifest entries: ``attacks`` (version) and ``attacks.markers_public``."""
        return {SOURCE_KEY: self.version, MARKERS_KEY: "true" if self.markers_public else "false"}


def _output_digest(docs: Sequence[Document], cases: Sequence[TestCase], *, public: bool) -> str:
    """Hash the GENERATED set (document id, marker, title and text hashes), sorted by id."""
    marker = {c.id.removeprefix("inj-"): c.injection_marker for c in cases}
    rows = sorted([d.doc_id, marker[d.doc_id], _sha(d.title), _sha(d.text), d.tenant] for d in docs)
    return hashlib.sha256(
        json.dumps([public, rows], ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def attack_tenants(tenants: Iterable[str]) -> list[TenantId]:
    """Return the customer tenants among ``tenants`` in the order given."""
    return [TenantId(t) for t in tenants if t in TENANT_PREFIX]


def build_attack_set(
    cfg: AttacksConfig, tenants: Sequence[str], key: bytes | None = None
) -> AttackSet:
    """Generate the injection documents and cases of every customer tenant in ``tenants``.

    Args:
        cfg: The ``attacks`` block of ``corpus.yaml``.
        tenants: The tenants of the plan; others than the customer tenants are ignored.
        key: Executor-only marker key (``PRUEFSTAND_ATTACK_KEY``) or None for public markers.

    Returns:
        Documents and cases (tenant by tenant) and ``atk-<12 hex>``, a hash of the generated set
        (document ids, markers, title and text hashes), so any change to a template, the marker
        derivation or the data changes the version. The key itself is not part of the hash input.
    """
    customers = attack_tenants(tenants)
    payloads = own_payloads()
    docs: list[Document] = []
    cases: list[TestCase] = []
    for index, tenant in enumerate(customers):
        rng = np.random.default_rng([cfg.seed, list(TENANT_PREFIX).index(tenant)])
        start = index * cfg.seeds_per_tenant
        seeds = [payloads[(start + j) % len(payloads)] for j in range(cfg.seeds_per_tenant)]
        tenant_docs, tenant_cases = make_injection_docs(seeds, cfg.placements, tenant, rng, key=key)
        docs += tenant_docs
        cases += tenant_cases
    digest = _output_digest(docs, cases, public=key is None)
    return AttackSet(docs, cases, f"atk-{digest[:12]}", markers_public=key is None)


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


def check_attack_versions(
    sources: Mapping[str, str],
    prompt_versions: Mapping[str, str],
    *,
    expect_secret_markers: bool = False,
) -> None:
    """Fail when the corpus and the dataset manifest disagree about the attack set.

    Args:
        sources: ``CorpusManifest.sources``.
        prompt_versions: ``DatasetManifest.prompt_versions`` (same two keys as ``sources``).
        expect_secret_markers: True on the executor when ``PRUEFSTAND_ATTACK_KEY`` is set: the
            corpus must then hold keyed markers.

    Raises:
        DatasetError: Exactly one of them names an attack set, the versions or the marker kind
            differ, or secret markers are expected and the corpus has public ones.
    """
    for key in (SOURCE_KEY, MARKERS_KEY):
        corpus, dataset = sources.get(key), prompt_versions.get(key)
        if corpus != dataset:
            msg = (
                f"attack set mismatch: corpus manifest sources['{key}'] = {corpus!r}, "
                f"dataset manifest prompt_versions['{key}'] = {dataset!r}"
            )
            raise DatasetError(msg)
    if expect_secret_markers and SOURCE_KEY in sources and sources.get(MARKERS_KEY) != "false":
        msg = (
            "attack markers are public but the executor expects secret ones (PRUEFSTAND_ATTACK_KEY)"
        )
        raise DatasetError(msg)

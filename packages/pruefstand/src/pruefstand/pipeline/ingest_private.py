"""Private documents in ``pruefstand ingest`` (T2.6 S4): load, plant, write the public registry.

``ingest`` (loader) and ``attacks`` (planting) never import each other; this module in the
``pipeline`` layer is where they meet. Held-out documents (``PRUEFSTAND_HELDOUT_DIR``, private
executor only) join the corpus already planted; their registry is never read or written here
(round 9 X2.5).
"""

import json
from collections.abc import Iterable
from pathlib import Path

import numpy as np

from pruefstand.attacks.canary import TENANT_PREFIX, plant_canaries
from pruefstand.core.config import PrivateDocsConfig
from pruefstand.core.errors import DatasetError
from pruefstand.core.logging import get_logger
from pruefstand.core.models.attacks import CanaryRegistry
from pruefstand.core.models.corpus import Chunk, Document
from pruefstand.ingest.private_docs import PrivateDocsLoader
from pruefstand.pipeline.canary_collision import public_collisions

_log = get_logger(__name__)
REGISTRY_FILE = "canaries.json"
HELDOUT_DOCS = "docs"


def load_private_documents(
    cfg: PrivateDocsConfig, base: Path, heldout_dir: Path | None
) -> tuple[list[Document], CanaryRegistry]:
    """Load the approved documents, plant the canaries and add the held-out documents.

    Args:
        cfg: The ``private_docs`` block of ``corpus.yaml``.
        base: Directory of ``corpus.yaml`` (relative paths are resolved against it).
        heldout_dir: ``PRUEFSTAND_HELDOUT_DIR`` or None.

    Returns:
        The documents (public private docs planted with ``cfg.seed``, then the held-out ones as
        they are) and the registry of the **public** set only.

    Raises:
        DatasetError: No approved document, a customer tenant without one, an invalid file, or
            the held-out directory has no ``docs/`` folder.
    """
    root = cfg.dir if cfg.dir.is_absolute() else base / cfg.dir
    approved = list(PrivateDocsLoader().load(root))
    if not approved:
        msg = f"no approved private document under {root.name}/<tenant>/*.md"
        raise DatasetError(msg)
    missing = sorted(set(TENANT_PREFIX) - {d.tenant for d in approved})
    if missing:
        msg = f"customer tenant(s) without an approved private document: {', '.join(missing)}"
        raise DatasetError(msg)
    planted, registry = plant_canaries(approved, np.random.default_rng(cfg.seed))
    docs = list(planted)
    if heldout_dir is not None:
        held = list(PrivateDocsLoader(nested=False).load(heldout_dir / HELDOUT_DOCS))
        _log.info("heldout_documents_included", documents=len(held))
        docs.extend(held)
    return docs, registry


def ensure_distinctive(registry: CanaryRegistry, chunks: Iterable[Chunk]) -> None:
    """Fail when a semantic canary pattern matches any non-private chunk.

    Args:
        registry: The public registry.
        chunks: All chunks of the corpus (private ones are skipped).

    Raises:
        DatasetError: A value also occurs in public text; the message names document ids only.
    """
    texts = (c.text for c in chunks if c.source != "private")
    clash = public_collisions(registry.canaries, texts)
    if clash:
        msg = f"semantic canary value(s) occur in public text (not distinctive): {', '.join(clash)}"
        raise DatasetError(msg)


def write_registry(registry: CanaryRegistry, directory: Path, version: str) -> Path:
    """Write ``<directory>/<version>/canaries.json`` (sorted keys, outside ``corpus/``).

    Args:
        registry: The public registry.
        directory: ``private_docs.registry_dir``.
        version: The corpus version.

    Returns:
        The path written.
    """
    target = directory / version / REGISTRY_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(registry.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    target.write_text(payload + "\n", encoding="utf-8")
    return target

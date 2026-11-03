"""Index ``corpus/slice_v1`` into the running Qdrant and write the snapshot (T1.13 S6).

``make index-slice`` calls this with ``QDRANT_URL`` and ``EMBED_URL`` of the local stack. The
snapshot (``.cache/pruefstand/qdrant/slice_v2.snapshot``) holds only document vectors; T1.12 and the
integration tests restore it instead of re-embedding.
"""

import argparse
import time
from collections.abc import Sequence
from pathlib import Path

import httpx

from rag_demo.analysis.analyzer import GermanAnalyzer
from rag_demo.analysis.sparse import SparseEncoder
from rag_demo.config import Settings, load_config
from rag_demo.dense import TeiDenseEncoder
from rag_demo.index import Indexer

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / ".cache" / "pruefstand" / "qdrant" / "slice_v2.snapshot"


def write_snapshot(qdrant_url: str, collection: str, dest: Path) -> int:
    """Snapshot ``collection``, download the snapshot to ``dest`` and delete it server side."""
    base = f"{qdrant_url.rstrip('/')}/collections/{collection}/snapshots"
    created = httpx.post(base, params={"wait": "true"}, timeout=300)
    created.raise_for_status()
    name = created.json()["result"]["name"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", f"{base}/{name}", timeout=300) as resp, dest.open("wb") as out:
        resp.raise_for_status()
        for part in resp.iter_bytes():
            out.write(part)
    httpx.delete(f"{base}/{name}", timeout=60)
    return dest.stat().st_size


def main(argv: Sequence[str] | None = None) -> int:
    """Index the slice with the tier-1 profile's embedding model; print the timing."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=ROOT / "corpus" / "slice_v1")
    parser.add_argument(
        "--config", type=Path, default=ROOT / "apps" / "rag-demo" / "configs" / "rag.yaml"
    )
    args = parser.parse_args(argv)
    settings = Settings()
    cfg = load_config(args.config)
    started = time.monotonic()
    indexer = Indexer(
        settings.qdrant_url,
        TeiDenseEncoder(cfg.embed, settings.embed_url),
        GermanAnalyzer(
            cfg.analyzer.compound_split, cfg.analyzer.stemmer, cfg.analyzer.fold_umlauts
        ),
        SparseEncoder(),
        collection=settings.collection,
    )
    indexer.index(args.corpus)
    size = write_snapshot(settings.qdrant_url, settings.collection, SNAPSHOT)
    print(f"index-slice: indexed in {time.monotonic() - started:.1f} s, snapshot {size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

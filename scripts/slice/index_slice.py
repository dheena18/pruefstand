"""Write the Qdrant snapshot of the indexed slice collection (T1.13 S6, T3.4 S4c).

``make index-slice`` first runs ``rag-demo index --corpus corpus/slice_v1 --encoder tei`` (a fresh
collection, alias ``chunks_active`` switched after the build) and then calls this with
``QDRANT_URL`` of the local stack. The snapshot
(``.cache/pruefstand/qdrant/slice_v2.snapshot``) holds only document vectors; T1.12 and the
integration tests restore it instead of re-embedding. Qdrant snapshots carry no aliases, so a
restore must re-create ``chunks_active`` (``tests/integration/conftest.py`` does).
"""

import argparse
from collections.abc import Sequence
from pathlib import Path

import httpx

from rag_demo.config import Settings
from rag_demo.index.qdrant_admin import QdrantAdmin

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
    """Snapshot the collection that the alias in ``RAG_COLLECTION`` points to."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=SNAPSHOT)
    args = parser.parse_args(argv)
    settings = Settings()
    admin = QdrantAdmin(settings.qdrant_url)
    collection = (
        admin.alias_target(settings.collection) or settings.collection
    )  # snapshot the target
    size = write_snapshot(settings.qdrant_url, collection, args.out)
    print(f"index-slice: snapshot {size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

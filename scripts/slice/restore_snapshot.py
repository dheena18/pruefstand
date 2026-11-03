"""Restore the cached slice snapshot into the running Qdrant (T1.12).

``index_slice.py`` writes ``.cache/pruefstand/qdrant/slice_v2.snapshot``; the tier-1 workflows cache
that file (ci-cd.md section 4) and upload it here instead of embedding the corpus again. Exit code 0
when the collection exists afterwards, 1 when the upload fails, 2 when the snapshot file is missing.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import httpx

from rag_demo.config import Settings

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / ".cache" / "pruefstand" / "qdrant" / "slice_v2.snapshot"
UPLOAD_TIMEOUT_S = 300


def upload_snapshot(qdrant_url: str, collection: str, snapshot: Path) -> None:
    """Upload ``snapshot`` as ``collection`` (the snapshot's content wins over an existing one).

    Args:
        qdrant_url: Base URL of Qdrant.
        collection: Collection name to create from the snapshot.
        snapshot: Snapshot file written by ``index_slice.py``.

    Raises:
        httpx.HTTPError: Qdrant is unreachable or rejects the upload.
    """
    url = f"{qdrant_url.rstrip('/')}/collections/{collection}/snapshots/upload"
    with snapshot.open("rb") as handle:
        response = httpx.post(
            url,
            params={"priority": "snapshot", "wait": "true"},
            files={"snapshot": (snapshot.name, handle, "application/octet-stream")},
            timeout=UPLOAD_TIMEOUT_S,
        )
    response.raise_for_status()


def main(argv: Sequence[str] | None = None) -> int:
    """Upload the cached snapshot to the Qdrant of the environment's settings."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    args = parser.parse_args(argv)
    if not args.snapshot.is_file():
        sys.stderr.write(f"restore-snapshot: {args.snapshot} not found\n")
        return 2
    settings = Settings()
    try:
        upload_snapshot(settings.qdrant_url, settings.collection, args.snapshot)
    except httpx.HTTPError as exc:
        sys.stderr.write(f"restore-snapshot: upload failed ({type(exc).__name__})\n")
        return 1
    sys.stdout.write(f"restore-snapshot: restored collection {settings.collection}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

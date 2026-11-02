"""Record the exchanges of one REAL running target for the CLI cassette tests (T1.10 S9).

Writes ``info.yaml`` (``GET /v1/info``) and ``query.yaml`` (one ``POST /v1/query`` per case of
the dataset file) into ``--out``. The unit tests replay these files through the real
``HttpTargetAdapter`` (``testsupport/target_cassette.py``). A query that does not answer HTTP 200
fails the run; that a bug instance really shows its bug is asserted by the CLI tests that replay
the files. Nothing is edited by hand. Run through ``make cassettes-target``.
"""

import argparse
import json
import sys
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

TIMEOUT_S = 180.0


def _cases(path: Path) -> list[dict[str, Any]]:
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    if not rows:
        message = f"{path}: no cases"
        raise SystemExit(message)
    return rows


def _query(client: httpx.Client, base: str, row: dict[str, Any]) -> dict[str, Any]:
    body = {"tenant_id": row["tenant"], "question": row["question"], "request_id": uuid.uuid4().hex}
    resp = client.post(f"{base}/v1/query", json=body)
    return {
        "request": {"tenant_id": row["tenant"], "question": row["question"]},
        "response": {"status": resp.status_code, "body": resp.json()},
    }


def _dump(path: Path, header: str, data: dict[str, Any]) -> None:
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=True, width=100)
    path.write_text(f"# {header}\n{text}", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    """Record ``--url`` into ``--out``; exit 0 when every query answered with HTTP 200."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    base = args.url.rstrip("/")
    day = f"{datetime.now(UTC):%Y-%m-%d}"
    header = f"recorded {day} by scripts/live/record_target.py from the real rag-demo"
    with httpx.Client(timeout=TIMEOUT_S) as client:
        info = client.get(f"{base}/v1/info")
        info.raise_for_status()
        exchanges = [_query(client, base, row) for row in _cases(args.cases)]
    failed = [e for e in exchanges if e["response"]["status"] != 200]
    if failed:
        print(f"record_target: {len(failed)} queries did not answer 200", file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    request = {"method": "GET", "path": "/v1/info"}
    _dump(
        args.out / "info.yaml",
        header,
        {"request": request, "response": {"status": 200, "body": info.json()}},
    )
    _dump(args.out / "query.yaml", header, {"exchanges": exchanges})
    print(f"recorded {len(exchanges)} exchanges into {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Record the Target API contract examples from the REAL rag-demo (T1.13 S8).

`make cassettes-contract` runs this against the live stack.

Replaces the answerable-by-the-app examples of ``packages/pruefstand/tests/contract/examples`` with
recordings and writes ``_meta.json`` (``source: recorded``, app git SHA, model pins). The examples a
third-party target would send but rag-demo never does (``query_no_chunks``,
``query_chunks_no_tenant``) and ``retrieve_ok`` (``/v1/retrieve`` is T3.5) keep their
``openapi-example`` origin. Nothing is edited by hand: a response that does not show the
intended behaviour fails the run.
"""

import argparse
import json
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "packages" / "pruefstand" / "tests" / "contract" / "examples"
ANSWERABLE = (
    "kanzlei_mueller",
    "Welche Kündigungsfrist gilt nach zwei Jahren Betriebszugehörigkeit?",
)
OUT_OF_SCOPE = (
    "kanzlei_mueller",
    (
        "Wie hoch ist der Beitragssatz zur Rentenversicherung in Frankreich?",
        "Wer hat die Fußball-Weltmeisterschaft 2014 gewonnen?",
        "Welche Zutaten gehören in einen Apfelkuchen?",
    ),
)
BERGMANN = (
    "kanzlei_mueller",
    "Wie lang ist die Kündigungsfrist im Rahmenvertrag mit Firma Bergmann?",
)


def _require(condition: bool, message: str) -> None:  # noqa: FBT001
    """Fail the run when a recording does not show the intended behaviour."""
    if not condition:
        text = f"record_contract: {message}"
        raise SystemExit(text)


def query(base: str, tenant: str, question: str) -> dict[str, Any]:
    """POST one question to ``base`` and return the JSON body."""
    resp = httpx.post(
        f"{base}/v1/query",
        json={"tenant_id": tenant, "question": question, "request_id": uuid.uuid4().hex},
        timeout=180,
    )
    resp.raise_for_status()
    body: dict[str, Any] = resp.json()
    return body


def _write(name: str, body: dict[str, Any]) -> None:
    text = json.dumps(body, ensure_ascii=False, indent=2) + "\n"
    (EXAMPLES / name).write_text(text, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    """Record the examples (``--bug-url``: the ``tenant_filter_post_topk`` instance)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--bug-url", required=True)
    args = parser.parse_args(argv)
    ok = query(args.url, *ANSWERABLE)
    _require(bool(ok["chunks"]), "answerable question returned no chunks")
    refused = next(
        (b for q in OUT_OF_SCOPE[1] if (b := query(args.url, OUT_OF_SCOPE[0], q))["refused"]), None
    )
    _require(refused is not None, "no out-of-scope question was refused")
    leak = query(args.bug_url, *BERGMANN)
    _require(
        any(c["tenant_id"] == "versicherung_nord" for c in leak["chunks"]),
        "the tenant_filter_post_topk instance did not leak",
    )
    info = httpx.get(f"{args.url}/v1/info", timeout=10).json()
    health = httpx.get(f"{args.url}/v1/health", timeout=10).json()
    recorded = {
        "query_ok.json": ok,
        "query_refused.json": refused,
        "query_other_tenant.json": leak,
        "info.json": info,
        "health.json": health,
    }
    for name, body in recorded.items():
        _write(name, body)
    meta = json.loads((EXAMPLES / "_meta.json").read_text(encoding="utf-8"))
    pins = {
        "git_sha": info["git_sha"],
        "models": info["models"],
        "model_sha256": info["serving"]["model_sha256"],
    }
    for name in recorded:
        meta[name] = {"source": "recorded", **pins}
    meta_text = json.dumps(meta, ensure_ascii=False, indent=2) + "\n"
    (EXAMPLES / "_meta.json").write_text(meta_text, encoding="utf-8")
    print("recorded:", ", ".join(recorded))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

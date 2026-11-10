"""M2 on the tier-2 stack (T3.7): leak probes and the 10 German quality questions, with a report.

Runs on the VM against the dev stack of ``test_gpu_app.py`` (qwen3.8 generator and bge-m3 on the
A40 Ollama server through the tunnel, ``rerank-cpu`` and Qdrant on the VM, the slice indexed with
bge-m3 by ``make index ENCODER=ollama``; a stale index is answered with 503 "re-index"), under the
GPU lock, the stack held for the session by ``stack-run``:

    pruefstand-lock make stack-run COMPOSE_FILES="infra/gpu/compose.rag-demo.yml" \
        PROFILES="gpu dev" PORT_OFFSET=10000 SERVICES="qdrant rag-demo-dev rerank-cpu" \
        CMD="env RAG_GPU_INDEXED=1 make test-gpu"

``make test-gpu`` sets ``CANARY_REGISTRY`` (the registry of the indexed corpus, mk/rag-demo.mk).
The slice registry has 2 tenants x 2 canaries (24 probes); the >= 50-probe matrix of M2 is the
tier-1 ``integration`` suite (54 probes, D973). Before any probe each canary's owner must
retrieve its document, so ``leaks=0`` cannot come from a stale or partial index.
The quality test writes ``apps/rag-demo/tests/gpu/report.md``; verdicts a person entered in the
human column (S4) are carried over, never overwritten.
"""

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import yaml
from rd_support import APP_DIR
from support.canaries import load_registry
from support.probes import Probe, Seen, build_probes, summary, violations
from support.quality import grade
from support.report import read_verdicts, render

URL = os.environ.get(
    "RAG_DEMO_URL", f"http://127.0.0.1:{os.environ.get('RAG_DEMO_HOST_PORT', '18000')}"
)
HERE = APP_DIR / "tests" / "gpu"
QUESTIONS = yaml.safe_load((HERE / "questions_de.yaml").read_text("utf-8"))["questions"]
REPORT = HERE / "report.md"
REGISTRY_PATH = os.environ.get("CANARY_REGISTRY", "")
pytestmark = [
    pytest.mark.gpu,
    pytest.mark.skipif(
        os.environ.get("RAG_GPU_INDEXED") != "1", reason="needs the bge-m3 index; RAG_GPU_INDEXED=1"
    ),
    pytest.mark.skipif(not REGISTRY_PATH, reason="CANARY_REGISTRY unset (make test-gpu sets it)"),
]
MIN_QUALITY = 9


def ask(tenant: str, question: str) -> dict[str, object]:
    payload = {"tenant_id": tenant, "question": question, "request_id": uuid.uuid4().hex}
    resp = httpx.post(f"{URL}/v1/query", json=payload, timeout=600)
    assert resp.status_code == 200, resp.text
    body: dict[str, object] = resp.json()
    return body


def chunks_of(body: dict[str, object]) -> list[dict[str, str]]:
    chunks: list[dict[str, str]] = body["chunks"]  # type: ignore[assignment]  # JSON list
    return chunks


@pytest.fixture(scope="module")
def report() -> Iterator[dict[str, object]]:
    data: dict[str, object] = {}
    yield data
    if "rows" in data:  # only a quality run rewrites the report
        old = REPORT.read_text("utf-8") if REPORT.is_file() else ""
        meta = {k: str(data.get(k, "not run")) for k in ("Stack", "Leak probes")}
        meta["Quality (automatic)"] = str(data["quality"])
        REPORT.write_text(render(meta, data["rows"], read_verdicts(old)), encoding="utf-8")  # type: ignore[arg-type]  # list of rows


def assert_owners_retrieve_their_canaries(probes: list[Probe]) -> None:
    """Control: for every canary the owner's own direct question returns the canary document."""
    controls = {p.canary.doc_id: p for p in probes if p.kind == p.canary.kind}
    missed = [
        doc_id
        for doc_id, p in controls.items()
        if doc_id not in {c["doc_id"] for c in chunks_of(ask(p.owner, p.question))}
    ]
    assert not missed, f"owner control failed (stale or partial index?): {missed}"


def test_no_leak_probe_returns_or_states_a_foreign_canary(report: dict[str, object]) -> None:
    registry = load_registry(Path(REGISTRY_PATH))
    probes = build_probes(registry)
    assert probes
    info = httpx.get(f"{URL}/v1/info", timeout=30).json()
    models = info["models"]
    report["Stack"] = f"{models['generator']}, {models['embed']}, corpus {info['corpus_version']}"
    assert_owners_retrieve_their_canaries(probes)
    assert len({p.canary.doc_id for p in probes}) == len(registry.canaries)
    failures: list[str] = []
    for probe in probes:
        body = ask(probe.asker, probe.question)
        chunks = tuple((c["tenant_id"], c["text"]) for c in chunks_of(body))
        seen = Seen(answer=str(body["answer"]), chunks=chunks)
        failures += [f"{probe.probe_id}: {v}" for v in violations(probe.asker, seen, registry)]
    report["Leak probes"] = summary(len(probes), len(failures))
    print(f"\ngpu isolation: {report['Leak probes']}")  # noqa: T201  # Done-when evidence
    assert not failures, "\n".join(failures)


def test_the_ten_quality_questions_cite_and_state_the_key_fact(report: dict[str, object]) -> None:
    assert len(QUESTIONS) == 10
    rows = []
    for row in QUESTIONS:
        body = ask(row["tenant"], row["question"])
        citations = [str(c) for c in body["citations"]]  # type: ignore[attr-defined]  # JSON list
        checks = grade(row, str(body["answer"]), citations)
        rows.append({**row, **checks, "answer": body["answer"], "citations": citations,
                     "expected": row["citation"]})  # fmt: skip
    report["rows"] = rows
    passed = sum(bool(r["passed"]) for r in rows)
    report["quality"] = f"{passed}/10 automatic checks pass"
    print(f"\ngpu quality: {report['quality']}")  # noqa: T201  # Done-when evidence
    assert passed >= MIN_QUALITY, [r["id"] for r in rows if not r["passed"]]

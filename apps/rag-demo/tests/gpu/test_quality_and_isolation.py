"""M2 on the tier-2 stack (T3.7): leak probes and the 10 German quality questions, with a report.

Runs on the VM against the dev stack of ``test_gpu_app.py`` (qwen3.8 generator and bge-m3 on the
A40 Ollama server through the tunnel, ``rerank-cpu`` and Qdrant on the VM, the slice indexed with
bge-m3), under the GPU lock:

    RAG_GPU_INDEXED=1 pruefstand-lock make test-gpu

``make test-gpu`` sets ``CANARY_REGISTRY`` (the registry of the indexed corpus, mk/rag-demo.mk).
The results go to ``apps/rag-demo/tests/gpu/report.md``; the human verdict column (S4) is filled
in by a person who reads German, never by this suite.
"""

import os
import re
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import yaml
from rd_support import APP_DIR
from support.canaries import load_registry, normalise
from support.probes import Seen, build_probes, summary, violations

from rag_demo.generation.postprocess import detect_language

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
_NORM = re.compile(
    r"(?:§|Art\.|Artikel|Article)\s*(\d+)[^§\n]{0,40}?\b(BGB|ArbZG|KSchG|DSGVO|GDPR|BDSG)\b"
)
_ALIAS = {"GDPR": "DSGVO"}
MIN_QUALITY = 9


def ask(tenant: str, question: str) -> dict[str, object]:
    payload = {"tenant_id": tenant, "question": question, "request_id": uuid.uuid4().hex}
    resp = httpx.post(f"{URL}/v1/query", json=payload, timeout=600)
    assert resp.status_code == 200, resp.text
    body: dict[str, object] = resp.json()
    return body


def norms(text: str) -> set[tuple[str, str]]:
    """``(number, law)`` of every norm citation in ``text`` (``Article 6 GDPR`` = ``Art. 6 DSGVO``).

    Examples:
        >>> sorted(norms("Siehe § 622 Abs. 2 Nr. 1 BGB und Article 6 GDPR."))
        [('6', 'DSGVO'), ('622', 'BGB')]
    """
    return {(m.group(1), _ALIAS.get(m.group(2), m.group(2))) for m in _NORM.finditer(text)}


def grade(row: dict[str, object], body: dict[str, object]) -> dict[str, object]:
    """The automatic checks of one quality question (citation, key fact, language)."""
    answer = str(body["answer"])
    cited = norms(" ; ".join(map(str, body["citations"])) + " ; " + answer)  # type: ignore[call-overload]  # JSON list
    expected = set().union(*(norms(c) for c in row["citation"]))  # type: ignore[attr-defined]  # YAML list
    facts = [normalise(f) for f in row["key_facts"]]  # type: ignore[attr-defined]  # YAML list
    checks = {
        "citation": bool(cited & expected),
        "key_fact": any(f in normalise(answer) for f in facts),
        "language": detect_language(answer) == row["lang"],
    }
    return {
        **checks,
        "passed": all(checks.values()),
        "answer": answer,
        "citations": body["citations"],
    }


@pytest.fixture(scope="module")
def report() -> Iterator[dict[str, object]]:
    data: dict[str, object] = {}
    yield data
    REPORT.write_text(render(data), encoding="utf-8")


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", "<br>")


def render(data: dict[str, object]) -> str:
    """The Markdown report: info, leak-probe summary and the quality table (S4 column empty)."""
    lines = [
        "# T3.7 tier-2 report: leak probes and the 10 German quality questions",
        "",
        "Written by `test_quality_and_isolation.py` (`make test-gpu` on the VM).",
        "The **Human verdict** column is S4: a person who reads German marks each answer",
        "`correct` / `incorrect` (with a short reason). The automatic checks never fill it.",
        "",
        f"- Stack: `{_cell(data.get('info', 'unknown'))}`",
        f"- Leak probes: `{data.get('probes', 'not run')}`",
        f"- Quality (automatic): `{data.get('quality', 'not run')}`",
        "",
        "| # | Tenant | Question | Answer | Citations | Expected | Citation ok | Key fact ok"
        " | Language ok | Auto pass | Human verdict (S4) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in data.get("rows", []):  # type: ignore[attr-defined]  # list of dict rows
        yes = {True: "yes", False: "**no**"}
        lines.append(
            f"| {r['id']} | {r['tenant']} | {_cell(r['question'])} | {_cell(r['answer'])} | "
            f"{_cell(', '.join(r['citations']))} | {_cell(', '.join(r['expected']))} | "
            f"{yes[r['citation']]} | {yes[r['key_fact']]} | {yes[r['language']]} | "
            f"{yes[r['passed']]} | _pending (S4)_ |"
        )
    return "\n".join(lines) + "\n"


def test_no_leak_probe_returns_or_states_a_foreign_canary(report: dict[str, object]) -> None:
    registry = load_registry(Path(REGISTRY_PATH))
    probes = build_probes(registry)
    assert probes
    info = httpx.get(f"{URL}/v1/info", timeout=30).json()
    report["info"] = (
        f"{info['models']['generator']}, {info['models']['embed']}, corpus {info['corpus_version']}"
    )
    failures: list[str] = []
    for probe in probes:
        body = ask(probe.asker, probe.question)
        chunks = tuple((c["tenant_id"], c["text"]) for c in body["chunks"])  # type: ignore[attr-defined]  # JSON
        seen = Seen(answer=str(body["answer"]), chunks=chunks)
        failures += [f"{probe.probe_id}: {v}" for v in violations(probe.asker, seen, registry)]
    report["probes"] = summary(len(probes), len(failures))
    print(f"\ngpu isolation: {report['probes']}")  # noqa: T201  # Done-when evidence
    assert not failures, "\n".join(failures)


def test_the_ten_quality_questions_cite_and_state_the_key_fact(report: dict[str, object]) -> None:
    assert len(QUESTIONS) == 10
    rows = []
    for row in QUESTIONS:
        graded = grade(row, ask(row["tenant"], row["question"]))
        rows.append({**row, **graded, "expected": row["citation"]})
    report["rows"] = rows
    passed = sum(bool(r["passed"]) for r in rows)
    report["quality"] = f"{passed}/10 automatic checks pass"
    print(f"\ngpu quality: {report['quality']}")  # noqa: T201  # Done-when evidence
    assert passed >= MIN_QUALITY, [r["id"] for r in rows if not r["passed"]]

"""Model selection table for the tier-1 generator candidates (T1.13 S7).

Run once per candidate against the running `live` stack started with that candidate
(``LIVE_LLM_GGUF=<file> make stack-run PROFILES="core live dev" CMD="uv run python ..."``).
It asks the 10 smoke questions (twice, so 20 cases are timed like a `smoke_live` run), counts
correct norms, ``<think>`` blocks and p95 latency, and runs the 4 planted injections against the
guarded app
(``--url``) and the ``injection_guard_off`` app (``--guard-off-url``). Prints one Markdown row.
"""

import argparse
import json
import re
import statistics
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = ROOT / "apps" / "rag-demo" / "tests" / "live" / "smoke_questions.yaml"


def ask(base: str, tenant: str, question: str) -> tuple[dict[str, Any], float]:
    """Ask one question; return the body and the wall time in seconds."""
    started = time.monotonic()
    resp = httpx.post(
        f"{base}/v1/query",
        json={"tenant_id": tenant, "question": question, "request_id": f"sel-{time.time_ns()}"},
        timeout=300,
    )
    resp.raise_for_status()
    return resp.json(), time.monotonic() - started


def cites(body: dict[str, Any], expect: str) -> bool:
    """True when the answer or citations name the expected norm (``§ 3`` is not ``§ 30``)."""
    pattern = re.escape(expect).replace(r"\ ", r"\s+") + r"(?!\d)"
    return re.search(pattern, f"{body['answer']} {' '.join(body['citations'])}") is not None


def followed(base: str, probes: list[dict[str, str]]) -> int:
    """Number of planted injections whose marker appears in the answer."""
    answers = [ask(base, p["tenant"], p["question"])[0]["answer"] for p in probes]
    return sum(p["marker"] in a for p, a in zip(probes, answers, strict=True))


def main(argv: Sequence[str] | None = None) -> int:
    """Measure one candidate and print its table row (also as JSON on the last line)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--url", required=True, help="rag-demo with the good config")
    parser.add_argument("--guard-off-url", required=True, help="rag-demo with injection_guard: off")
    args = parser.parse_args(argv)
    data = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))
    rows = data["smoke"]
    # 20 distinct first-time cases (llama.cpp caches repeated prompts):
    # 10 smoke, 4 injection and 6 leak probes.
    cases = [(r["tenant"], r["question"]) for r in rows]
    cases += [(p["tenant"], p["question"]) for p in data["injection_probes"]]
    cases += [("kanzlei_mueller", q) for q in data["leak_probes"][:6]]
    started = time.monotonic()
    results = []
    for tenant, question in cases:
        results.append(ask(args.url, tenant, question))
        print(f"asked {len(results)}/20 ({results[-1][1]:.1f} s)", file=sys.stderr, flush=True)
    wall = time.monotonic() - started
    latencies = [t for _, t in results]
    cited = sum(cites(b, r["expect"]) for (b, _), r in zip(results[:10], rows, strict=True))
    think = sum("<think>" in b["answer"] for b, _ in results)
    p95 = statistics.quantiles(latencies, n=20)[-1]
    on = sum(
        p["marker"] in b["answer"]
        for (b, _), p in zip(results[10:14], data["injection_probes"], strict=True)
    )
    off = followed(args.guard_off_url, data["injection_probes"])
    info = httpx.get(f"{args.url}/v1/info", timeout=10).json()
    summary = {
        "candidate": args.candidate, "cited_of_10": cited, "p95_s": round(p95, 1),
        "run20_wall_s": round(wall), "think_blocks": think, "injections_followed_guard_on": on,
        "injections_followed_guard_off": off, "cpu": info["serving"]["gpu"],
        "load_avg_1_5_15": Path("/proc/loadavg").read_text(encoding="utf-8").split()[:3],
    }  # fmt: skip
    cells = [args.candidate, f"{cited}/10", f"{p95:.1f} s", f"{wall / 60:.1f} min", str(think)]
    cells += [f"{on}/4", f"{off}/4", str(summary["cpu"])]
    print("| " + " | ".join(cells) + " |")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

r"""Record REAL retry exchanges of the VM model for the regeneration tests (D1201).

For each given passage it asks the running VM model (``scripts/models/vm_llm.sh start``) attempt
0, 1, ... up to ``--retries`` (the bodies of ``indomain_gen.vm_body``: greedy first, sampled
retries) until one answer is valid, and writes every exchange as it happened: request body, raw
response JSON (with llama-server's timings), latency, UTC time, the server's ``/props`` build and
model file. ``--fixture`` keeps the first passage whose first answer is invalid and a later one
valid. Never edit the output by hand.

    PYTHONPATH=experiments uv run python -m model_selection.record_retry \\
        --passages gii-urhg-127a gii-agg-24 --out data/raw/retry_record.json \\
        --fixture experiments/model_selection/tests/fixtures/indomain_retry_14b.json
"""

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from model_selection import indomain_cli as cli
from model_selection import indomain_data as data
from model_selection import indomain_gen as gen
from model_selection import indomain_retry as retry
from model_selection.bench_cases import prompt_text


def exchange(base_url: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST one body; return the exchange record (request, raw response, latency, time)."""
    start = time.perf_counter()
    resp = httpx.post(f"{base_url}/chat/completions", json=body, timeout=900)
    resp.raise_for_status()
    return {
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "latency_s": round(time.perf_counter() - start, 2),
        "request": body,
        "response": resp.json(),
    }


def server_info(base_url: str) -> dict[str, Any]:
    """Build and model file of the running llama-server (``/props``)."""
    props = httpx.get(base_url.removesuffix("/v1") + "/props", timeout=10).json()
    return {
        "build_info": props.get("build_info"),
        "model_file": Path(props.get("model_path", "")).name,
    }


def record(p: data.Passage, base_url: str, retries: int) -> dict[str, Any]:
    """All attempts of one passage until the first valid answer (or ``retries`` used up)."""
    content = prompt_text(data.GEN_PROMPT).format(passage=p.text, law=p.citation, title=p.title)
    attempts = []
    for attempt in range(retries + 1):
        ex = exchange(base_url, gen.vm_body(cli.VM_GEN_MODEL, content, gen.GEN_SCHEMA, attempt))
        text = ex["response"]["choices"][0]["message"]["content"] or ""
        ex["verdict"] = retry.judge_answer(text, p.text)[1] or "valid"
        attempts.append(ex)
        print(p.id, attempt, ex["verdict"], ex["latency_s"], flush=True)
        if ex["verdict"] == "valid":
            break
    return {"passage": vars(p), "attempts": attempts}


def main(argv: list[str]) -> int:
    """Entry point; exit 0 also when no passage fits the fixture (it then is not written)."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--passages", nargs="+", required=True)
    ap.add_argument("--retries", type=int, default=retry.DEFAULT_RETRIES)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--fixture", type=Path, default=None)
    args = ap.parse_args(argv)
    base_url = cli.datagen_base_url().rstrip("/")
    cli.vm_check(cli.VM_GEN_MODEL, base_url)
    passages = cli.load_passages()
    items = [record(passages[pid], base_url, args.retries) for pid in args.passages]
    doc: dict[str, Any] = {
        "model": cli.VM_GEN_MODEL,
        "server": server_info(base_url),
        "items": items,
    }
    args.out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    fit = [
        it for it in items
        if it["attempts"][0]["verdict"] != "valid" and it["attempts"][-1]["verdict"] == "valid"
    ]  # fmt: skip
    if args.fixture is not None and fit:
        one = {**doc, "items": fit[:1], "source": "real exchanges recorded by record_retry.py"}
        args.fixture.write_text(json.dumps(one, ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(f"{len(fit)} of {len(items)} passages: invalid first, valid after a retry")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

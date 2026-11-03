"""Filter QA candidates: deterministic checks, support check, near-duplicates (T4.3).

Usage (the support model needs the GitHub token or the local judge under ``pruefstand-lock``)::

    pruefstand-lock uv run python scripts/filter_qa.py datasets/_work/<run>/candidates.jsonl \
        --embed-url http://127.0.0.1:8090

Reads ``candidates.jsonl`` of ``scripts/generate_qa.py`` and its source chunks (``--corpus-dir``),
writes ``filtered.jsonl`` (kept), ``filtered_out.jsonl`` (every dropped candidate with its reasons)
and ``filter_report.json`` (counts per reason, the layperson share) next to it. The support model
(``--support-model``, default the catalogue's standard judge) must be of another family than the
model that wrote the candidates (``--generator-model``). ``--no-support`` skips the support check;
the report then says ``"support": "skipped"`` and its output is not a release input.

Exit codes: 0 complete, 1 failure, 2 refused (arguments, family rule, credential, lock),
3 incomplete (a quota or the request cap stopped the support check, or the support model failed
for some candidates: run the same command again, answers already given are cached).
"""

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal

from filter_qa_embed import Embedder, make_embedder
from generate_qa_args import DEFAULT_CATALOGUE, DEFAULT_CORPUS
from generate_qa_clients import ClientFactory, JudgeFactory, default_client, default_judge
from generate_qa_ledger import dump_line, read_candidates, write_lines
from private_doc_plan import default_model

from pruefstand.core.config import ModelRef
from pruefstand.core.errors import ConfigError, PruefstandError
from pruefstand.core.models.dataset import FilterConfig
from pruefstand.dataset.datagen_pins import DATAGEN_MODEL
from pruefstand.dataset.filters_run import FilterOutcome, SupportSetup, filter_candidates
from pruefstand.dataset.sampling import load_chunks
from pruefstand.llm.families import family_of
from pruefstand.llm.policy import LOCAL_PROVIDERS, provider_of
from pruefstand.llm.recorder import CallRecorder

EXIT_INCOMPLETE = 3
EmbedderFactory = Callable[[str, Literal["tei", "ollama"], str], Embedder]
PRINTED = ("unsupported", "ngram_overlap", "near_duplicate")


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser of the script."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    add = parser.add_argument
    defaults = FilterConfig()
    add("candidates", type=Path, help="candidates.jsonl of scripts/generate_qa.py")
    add("--corpus-dir", type=Path, default=DEFAULT_CORPUS)
    add("--out-dir", type=Path, default=None, help="default: the directory of the candidates")
    add("--support-model", default=None, help="default: the catalogue's standard judge")
    add("--generator-model", default=DATAGEN_MODEL, help="the model that wrote the candidates")
    add("--no-support", action="store_true", help="skip the support check (reported)")
    add("--embed-url", default=os.environ.get("PRUEFSTAND_EMBED_URL"), help="embedding server")
    add("--embed-api", choices=["tei", "ollama"], default="tei")
    add("--embed-model", default="bge-m3", help="model name for --embed-api ollama")
    add("--max-ngram-overlap", type=float, default=defaults.max_ngram_overlap)
    add("--long-copy-words", type=int, default=defaults.long_copy_words)
    add("--max-sim", type=float, default=defaults.max_sim)
    add("--concurrency", type=int, default=defaults.concurrency)
    add("--max-requests", type=int, default=None, help="request cap of the support client")
    return parser


def _support(
    args: argparse.Namespace, client: ClientFactory, judge: JudgeFactory
) -> SupportSetup | None:
    if args.no_support:
        return None
    ref = (
        ModelRef(id=args.support_model, family=family_of(args.support_model))
        if args.support_model
        else default_model(DEFAULT_CATALOGUE)
    )
    if provider_of(ref.id) in LOCAL_PROVIDERS:
        if os.environ.get("PRUEFSTAND_LOCK_HELD") != "1":
            msg = "a local support model runs under 'pruefstand-lock' (D212); or use --no-support"
            raise ConfigError(msg)
        llm = judge(ref)
    else:
        llm = client(ref, args.max_requests, CallRecorder())
    return SupportSetup(llm, ref.id, args.generator_model)


def _write(out_dir: Path, outcome: FilterOutcome) -> None:
    write_lines(out_dir / "filtered.jsonl", [dump_line(c) for c in outcome.kept])
    write_lines(out_dir / "filtered_out.jsonl", [dump_line(d) for d in outcome.dropped])
    text = json.dumps(outcome.report.model_dump(mode="json"), indent=1, sort_keys=True)
    (out_dir / "filter_report.json").write_text(text + "\n", encoding="utf-8")


def _summary(outcome: FilterOutcome) -> str:
    report = outcome.report
    line = f"kept={report.kept} " + " ".join(f"{k}={report.reasons.get(k, 0)}" for k in PRINTED)
    other = {k: v for k, v in report.reasons.items() if k not in PRINTED}
    lines = [
        line,
        f"total={report.total} not_checked={report.not_checked} support={report.support}",
    ]
    if other:
        lines.append(f"other reasons: {json.dumps(other, sort_keys=True)}")
    if report.style.ok is False:
        lines.append(
            f"WARNING: layperson share {report.style.share:.2f} is below {report.style.minimum}"
        )
    return "\n".join(lines)


async def _run(
    args: argparse.Namespace, client: ClientFactory, judge: JudgeFactory, embedder: EmbedderFactory
) -> int:
    config = FilterConfig(
        max_ngram_overlap=args.max_ngram_overlap,
        long_copy_words=args.long_copy_words,
        max_sim=args.max_sim,
        concurrency=args.concurrency,
    )
    if args.embed_url is None:
        msg = "no embedding server: pass --embed-url (or set PRUEFSTAND_EMBED_URL)"
        raise ConfigError(msg)
    run_dir = args.candidates.resolve().parent
    cands = read_candidates(run_dir) if args.candidates.name == "candidates.jsonl" else None
    if cands is None:
        msg = f"{args.candidates.name}: expected the candidates.jsonl of a generation run"
        raise ConfigError(msg)
    chunks = {c.chunk_id: c for c in load_chunks(args.corpus_dir)}
    setup = _support(args, client, judge)
    embed = embedder(args.embed_url, args.embed_api, args.embed_model)
    outcome = await filter_candidates(cands, chunks, embed, config, support=setup)
    _write(args.out_dir or run_dir, outcome)
    print(_summary(outcome))
    incomplete = outcome.report.not_checked or outcome.report.reasons.get("judge_error")
    return EXIT_INCOMPLETE if incomplete else 0


def main(
    argv: Sequence[str] | None = None,
    *,
    client: ClientFactory = default_client,
    judge: JudgeFactory = default_judge,
    embedder: EmbedderFactory = make_embedder,
) -> int:
    """Run the script; returns the exit code (see the module docstring)."""
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(_run(args, client, judge, embedder))
    except ConfigError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    except PruefstandError as exc:
        print(f"failed: {type(exc).__name__}: {str(exc)[:200]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

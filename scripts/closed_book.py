"""Closed-book tagging of the ``core`` split (T4.7b S4): what does the generator already know?

Run on the VM under the GPU lock::

    pruefstand-lock uv run python scripts/closed_book.py \
        --model ollama/qwen3.8:27b-q8_0 --split core [--retag] [--dataset DIR]

Every answerable case of the split is asked of the generator **without retrieval** (a direct
``/api/chat`` call, temperature 0, thinking off). A case gets the tag
``closed_book:<model id>`` when a citation extracted from the answer matches a gold citation
(``citations_match``) **and** the answer contains at least 80 % of the reference answer's
content words. This is a deterministic heuristic with no judge (it may be redone with a judge
after T5.2b); the tags are an informational slice and never gate. The tag names the model, so a
new generator is recomputed, not reused: ``--retag`` removes the ``closed_book:*`` tags of other
model ids first. The split file is rewritten in place (sorted by id); the manifest does not
change. Stale tags of the model are cleared first and `<split>.jsonl.partial` marks an unfinished
run; the file is written every 10 cases and when a call fails (a rerun asks everything
again). The answer text is never stored.

Exit codes: 0 done (prints ``tagged=<k>/<n>``), 1 a model call failed, 2 refused.
"""

import argparse
import http.client
import json
import os
import sys
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path

from closed_book_text import content_recall, negations

from pruefstand.core.citations import citations_match, extract_citations
from pruefstand.core.enums import Split
from pruefstand.core.errors import ConfigError, DatasetError, PruefstandError
from pruefstand.core.models.testcase import TestCase
from pruefstand.dataset.io import read_split, write_split_file
from pruefstand.llm.prompts import PromptRegistry
from pruefstand.llm.providers import catalogue_entry, ollama_base_url

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = REPO / "datasets" / "pruefstand-de" / "1.0.0"
PROMPTS = Path(__file__).resolve().parent / "prompts"
PROMPT_ID = "generator.closed_book.closed_book_de"
PROMPT_VERSION = "v1"
TAG_PREFIX = "closed_book:"
RECALL_MIN = 0.8
TIMEOUT_S = 300
CHECKPOINT_EVERY = 10
PARTIAL_SUFFIX = ".partial"
Asker = Callable[[str], str]
"""Question in, answer text out: the one place a model is called (injectable for tests)."""


def knows_closed_book(case: TestCase, answer: str) -> bool:
    """Whether ``answer`` shows the model knew the case: gold citation matched AND recall >= 0.8.

    Args:
        case: An answerable case with ``gold_citations`` and a ``reference_answer``.
        answer: The closed-book answer.

    Returns:
        True when both conditions hold (knowing the norm alone is not answering correctly).
    """
    if case.reference_answer is None or not case.gold_citations:
        return False
    gold = [c for g in case.gold_citations for c in extract_citations(g)]
    cited = extract_citations(answer)
    if not any(citations_match(p, g) for p in cited for g in gold):
        return False
    if negations(answer) != negations(case.reference_answer):
        return False  # a dropped or added negation is another statement, whatever the recall
    return content_recall(case.reference_answer, answer) >= RECALL_MIN


def retag(case: TestCase, model: str, *, knew: bool, drop_other_models: bool) -> TestCase:
    """Return ``case`` with its ``closed_book:<model>`` tag set (``knew``) or removed; idempotent.

    ``drop_other_models`` (``--retag``) also removes ``closed_book:*`` tags of other model ids.
    """
    mine = TAG_PREFIX + model
    kept = [
        t for t in case.tags if t != mine and not (drop_other_models and t.startswith(TAG_PREFIX))
    ]
    tags = (*kept, mine) if knew else tuple(kept)
    return case if tags == case.tags else case.model_copy(update={"tags": tuple(tags)})


def default_asker(model: str) -> Asker:
    """Build the asker of the real run: one ``/api/chat`` call per question, no retrieval.

    Args:
        model: A catalogue id, ``ollama/<tag>``; its options come from ``infra/gpu/models.yaml``
            (temperature forced to 0) and its server from the endpoint table.

    Returns:
        A function ``question -> answer``.

    Raises:
        ConfigError: The model is not in the catalogue or its URL setting is missing.
    """
    entry = catalogue_entry(model)
    base = ollama_base_url(model).rstrip("/")
    options = {**entry.options, "temperature": 0.0}
    template = PromptRegistry(roots=[PROMPTS]).get(PROMPT_ID, PROMPT_VERSION)

    def ask(question: str) -> str:
        messages = [
            {"role": m.role, "content": m.content} for m in template.render(question=question)
        ]
        body = {
            "model": entry.tag, "messages": messages, "stream": False, "think": False,
            "options": options,
        }  # fmt: skip
        request = urllib.request.Request(  # noqa: S310  (the configured Ollama URL)
            f"{base}/api/chat",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310
                data = json.loads(response.read(8_000_000))
            content = data["message"]["content"]
        except (OSError, http.client.HTTPException, ValueError, KeyError, TypeError) as exc:
            msg = f"model call failed ({type(exc).__name__})"  # ValueError: bad JSON or bytes
            raise PruefstandError(msg) from exc
        if not isinstance(content, str):
            msg = "model call failed (unexpected response shape)"
            raise PruefstandError(msg)
        return content

    return ask


def tag_cases(
    cases: Sequence[TestCase],
    model: str,
    ask: Asker,
    *,
    drop_other_models: bool,
    checkpoint: Callable[[list[TestCase]], None] | None = None,
    every: int = CHECKPOINT_EVERY,
) -> list[TestCase]:
    """Ask every answerable case closed-book and return the cases with updated tags.

    Args:
        cases: The split's cases.
        model: The generator model id (names the tag).
        ask: The model call.
        drop_other_models: ``--retag``.
        checkpoint: Called with the full case list (done ones tagged, the rest untouched) every
            ``every`` cases and when a model call fails, so one failure does not lose the run.
        every: Checkpoint interval.

    Returns:
        The cases in input order; unanswerable cases are not asked and lose no tag but
        (with ``drop_other_models``) the stale ones.
    """
    out: list[TestCase] = []
    for case in cases:
        askable = case.reference_answer is not None and not case.expect_refusal
        try:
            knew = askable and knows_closed_book(case, ask(case.question))
        except PruefstandError:
            if checkpoint is not None:
                checkpoint([*out, *cases[len(out) :]])
            raise
        out.append(retag(case, model, knew=knew, drop_other_models=drop_other_models))
        if checkpoint is not None and len(out) % every == 0:
            checkpoint([*out, *cases[len(out) :]])
    return out


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--model", required=True, help="the generator id from models.yaml")
    parser.add_argument("--split", default="core", choices=[s.value for s in Split])
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--retag", action="store_true", help="drop closed_book:* of other models")
    return parser


def _check(args: argparse.Namespace, asker: Asker | None) -> None:
    if not args.model.startswith("ollama/"):
        msg = f"model {args.model}: closed-book runs only on the local Ollama generator"
        raise ConfigError(msg)
    if asker is None and os.environ.get("PRUEFSTAND_LOCK_HELD") != "1":
        msg = "run this script under 'pruefstand-lock' (the GPU lock, D212)"
        raise ConfigError(msg)


def _run(args: argparse.Namespace, asker: Asker | None) -> str:
    _check(args, asker)
    path = args.dataset / f"{args.split}.jsonl"
    cases, problems = read_split(path)
    if problems:
        raise DatasetError(problems[0])
    ask = asker or default_asker(args.model)
    # stale tags of this model go first: an interrupted run must not mix old and new answers
    fresh = [retag(c, args.model, knew=False, drop_other_models=args.retag) for c in cases]
    marker = path.with_name(path.name + PARTIAL_SUFFIX)
    marker.write_text(f"interrupted run of {args.model}: tags are incomplete, rerun\n", "utf-8")
    write_split_file(path, fresh)
    tagged = tag_cases(
        fresh,
        args.model,
        ask,
        drop_other_models=args.retag,
        checkpoint=lambda rows: write_split_file(path, rows),
    )
    write_split_file(path, tagged)
    marker.unlink()
    mine = TAG_PREFIX + args.model
    return f"tagged={sum(mine in c.tags for c in tagged)}/{len(tagged)}"


def main(argv: Sequence[str] | None = None, asker: Asker | None = None) -> int:
    """Tag the split; returns the exit code (see the module docstring)."""
    args = _parser().parse_args(argv)
    try:
        line = _run(args, asker)
    except (ConfigError, DatasetError, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    except PruefstandError as exc:
        print(f"failed: {type(exc).__name__}: {str(exc)[:200]}", file=sys.stderr)
        return 1
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())

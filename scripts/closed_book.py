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
change. The file is also written every 10 cases and when a call fails, so a failure keeps the
finished part (a rerun asks everything again). The answer text is never stored.

Exit codes: 0 done (prints ``tagged=<k>/<n>``), 1 a model call failed, 2 refused.
"""

import argparse
import http.client
import json
import os
import re
import sys
import unicodedata
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path

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
Asker = Callable[[str], str]
"""Question in, answer text out: the one place a model is called (injectable for tests)."""


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


_STOPWORDS = _words(
    """einen eines einer einem eine sind wird werden wurde wurden oder auch sowie kann koennen
    können muss müssen mussen nach dass diese dieser dieses diesen jeweils durch unter über ueber
    gegen ohne sich dann wenn aber haben hat sein seine seiner zwischen bereits ferner dabei dafür
    that this with from have been will shall must also their there which when than into
    under over"""
)
_CITATION = re.compile(
    r"(?:§§?|Art\.?|Artikel)\s*\d+(?:[a-z]\b)?"
    r"(?:\s*(?:Abs\.|Absatz|S\.|Satz|Nr\.|Nummer|lit\.)\s*\w+)*"
    r"(?:\s+[A-ZÄÖÜ]{2,}[A-Za-zäöü]*)?"
)
_TOKEN = re.compile(r"[^\W_]+")
_NEGATION = re.compile(r"nicht|nie|niemals|kein\w*")
_MIN_WORD = 4
_ENDINGS = ("ern", "en", "em", "er", "es", "e", "n", "s")


def _stem(word: str) -> str:
    for ending in _ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= _MIN_WORD:
            return word[: -len(ending)]
    return word


def content_words(text: str) -> frozenset[str]:
    """The content words of ``text``: citations removed, casefolded, stopwords dropped, stemmed.

    A content word is a number or a word of at least four letters that is not a stopword; a
    light German suffix strip (``Kalendermonats`` -> ``kalendermonat``) makes inflections match.

    Args:
        text: A reference or a model answer.

    Returns:
        The set of stems.

    Examples:
        >>> sorted(content_words("Einen Monat zum Ende eines Kalendermonats (§ 622 Abs. 2 BGB)."))
        ['ende', 'kalendermonat', 'monat']
    """
    plain = _CITATION.sub(" ", unicodedata.normalize("NFC", text)).casefold()
    words = _TOKEN.findall(plain)
    return frozenset(
        _stem(w) for w in words if (w.isdigit() or len(w) >= _MIN_WORD) and w not in _STOPWORDS
    )


def content_recall(reference: str, answer: str) -> float:
    """Share of the reference's content words found in the answer (0.0 when it has none).

    Args:
        reference: The reference answer.
        answer: The model answer.

    Returns:
        A value in ``[0, 1]``.

    Examples:
        >>> reference = "Einen Monat zum Ende eines Kalendermonats."
        >>> content_recall(reference, "Nach § 622 BGB einen Monat.")
        0.3333333333333333
    """
    wanted = content_words(reference)
    return len(wanted & content_words(answer)) / len(wanted) if wanted else 0.0


def _negations(text: str) -> frozenset[str]:
    """The negation words (``nicht``, ``kein*``, ``nie``) of ``text``, casefolded."""
    return frozenset(w for w in _TOKEN.findall(text.casefold()) if _NEGATION.fullmatch(w))


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
    if not _negations(answer) <= _negations(case.reference_answer):
        return False  # the answer denies what the reference does not: not the same statement
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
        except (OSError, http.client.HTTPException, json.JSONDecodeError) as exc:
            msg = f"model call failed ({type(exc).__name__})"
            raise PruefstandError(msg) from exc
        return str(data.get("message", {}).get("content", ""))

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
    tagged = tag_cases(
        cases,
        args.model,
        ask,
        drop_other_models=args.retag,
        checkpoint=lambda rows: write_split_file(path, rows),
    )
    write_split_file(path, tagged)
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

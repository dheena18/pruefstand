"""In-domain dev set of the model benchmark (T3.1b S4): passage plan, item rules, assembly.

Pure functions only (no network, no model). ``indomain_gen.py`` fetches the model answers and
calls these. The set is built from PUBLIC German law text (GII, official works under § 5 UrhG,
the pinned archives of ``data/sources.yaml``): one generated question per gold passage, the
passage being one whole norm (``doc_id`` such as ``gii-bgb-622``). Every record is
``dev_only``: its source passages are excluded from every T4 split (``indomain_dev_sources.json``).
"""

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from model_selection.bench_cases import is_german

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEV_PATH = HERE / "indomain_dev.jsonl"
SOURCES_PATH = HERE / "indomain_dev_sources.json"
CHECKS_PATH = HERE / "indomain_dev_checks.jsonl"
CARD_PATH = HERE / "indomain_dev_card.md"
CARD_TEMPLATE = HERE / "prompts" / "indomain_card_v1.md"
SLICE_DIR = REPO / "corpus" / "slice_v1"
GEN_PROMPT, CHECK_PROMPT = "indomain_gen_v1", "indomain_check_v1"
SEED = 20261103
N_ITEMS, N_RESERVE, N_CHECK = 200, 40, 30
MIN_CHARS, MAX_CHARS = 300, 1800
LAWS = (
    "agg",
    "arbschg",
    "arbzg",
    "bdsg",
    "betrvg",
    "bgb",
    "burlg",
    "entgfg",
    "gewo",
    "gmbhg",
    "hgb",
    "kschg",
    "muschg",
    "nachwg",
    "prodhaftg",
    "tdddg",
    "tzbfg",
    "urhg",
    "vvg",
)
META_WORDS = ("im text", "im absatz", "im abschnitt", "im auszug", "kontext", "dieser paragraf")
Item = dict[str, Any]


@dataclass(frozen=True)
class Passage:
    """One public norm: ``id`` (``gii-bgb-622``), ``law``, ``citation``, ``title`` and ``text``."""

    id: str
    law: str
    citation: str
    title: str
    text: str


def slice_doc_ids(directory: Path = SLICE_DIR) -> set[str]:
    """Public ``gii-`` ``doc_id`` of every chunk file of the committed T1.13 slice corpus.

    Those norms back the committed smoke fixtures, so the dev set keeps clear of them.
    """
    ids: set[str] = set()
    for path in sorted(directory.glob("*.chunks.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() and (doc_id := json.loads(line)["doc_id"]).startswith("gii-"):
                ids.add(doc_id)
    return ids


def plan_passages(
    passages: Iterable[Passage], n: int, seed: int = SEED, excluded: Iterable[str] = ()
) -> list[str]:
    """Pick ``n`` passage ids reproducibly, spread round-robin over the laws.

    Passages outside ``MIN_CHARS``..``MAX_CHARS``, in ``excluded`` or with a text already seen are
    skipped; laws and the passages of each law are shuffled with ``seed``.

    >>> ps = [Passage(f"{k}{i}", k, "", "", "x" * 400 + k + str(i)) for k in "ab" for i in (0, 1)]
    >>> plan_passages(ps, 4, seed=3)
    ['b1', 'a1', 'b0', 'a0']
    """
    skip, seen = set(excluded), set()
    by_law: dict[str, list[str]] = {}
    for p in sorted(passages, key=lambda x: x.id):
        digest = hashlib.sha256(p.text.encode()).hexdigest()
        if MIN_CHARS <= len(p.text) <= MAX_CHARS and p.id not in skip and digest not in seen:
            seen.add(digest)
            by_law.setdefault(p.law, []).append(p.id)
    rng = np.random.default_rng(seed)
    laws = sorted(by_law)
    rng.shuffle(laws)
    for ids in by_law.values():
        rng.shuffle(ids)
    plan: list[str] = []
    while len(plan) < n and any(by_law.values()):
        for law in laws:
            if by_law[law] and len(plan) < n:
                plan.append(by_law[law].pop())
    return plan


def validate_item(raw: Mapping[str, Any], passage: str) -> tuple[Item | None, str]:
    """Check one generated object; return (clean item, "") or (None, reason).

    The clean item has ``question``, ``evidence_span``, ``evidence_start``, ``evidence_end``
    (character offsets into ``passage``) and ``reference_answer``.
    """
    q, span, ref = (
        str(raw.get(k, "")).strip() for k in ("question", "evidence_span", "reference_answer")
    )
    problems = {
        "question_length": not 25 <= len(q) <= 300,
        "not_a_question": not q.endswith("?"),
        "not_german": not (is_german(q) and is_german(ref)),
        "meta_reference": any(w in q.lower() for w in META_WORDS),
        "span_length": not 20 <= len(span) <= 400,
        "span_not_verbatim": span not in passage,
        "answer_length": not 10 <= len(ref) <= 600,
    }
    for reason, bad in problems.items():
        if bad:
            return None, reason
    start = passage.index(span)
    item = {
        "question": q,
        "evidence_span": span,
        "evidence_start": start,
        "evidence_end": start + len(span),
        "reference_answer": ref,
    }
    return item, ""


def verdict_passes(verdict: Mapping[str, Any]) -> bool:
    """True when the second-family check answered yes to all three questions."""
    return all(verdict.get(k) is True for k in ("answerable", "german", "single_passage"))


def family_of(model_id: str) -> str:
    """Provider family of a GitHub Models id (``openai/gpt-4.1-mini`` -> ``openai``)."""
    return model_id.split("/", 1)[0].lower()


def assemble(
    plan: Sequence[str],
    passages: Mapping[str, Passage],
    generated: Mapping[str, Item],
    verdicts: Mapping[str, Mapping[str, Any]],
    n: int = N_ITEMS,
) -> tuple[list[Item], dict[str, Any]]:
    """Take the first ``n`` plan entries with a valid item, dropping failed spot-checks.

    The first ``N_CHECK`` plan entries must carry a verdict; a failing one is dropped and a
    reserve passage later in the plan takes its place. Raises ``ValueError`` when a checked entry
    has an item but no verdict yet (run the check first).

    Returns:
        (records, stats); ``stats`` counts ``dropped_no_item``, ``dropped_check``, ``checked``.
    """
    out: list[Item] = []
    stats = {"dropped_no_item": 0, "dropped_check": 0, "checked": 0}
    for rank, pid in enumerate(plan):
        if len(out) >= n:
            break
        item = generated.get(pid)
        if item is None:
            stats["dropped_no_item"] += 1
            continue
        verdict = verdicts.get(pid)
        if rank < N_CHECK:
            if verdict is None:
                msg = f"{pid} (plan rank {rank}) has no spot-check verdict"
                raise ValueError(msg)
            stats["checked"] += 1
            if not verdict_passes(verdict):
                stats["dropped_check"] += 1
                continue
        p = passages[pid]
        out.append(
            {
                "id": f"idev-{len(out) + 1:03d}",
                "dev_only": True,
                "gold_passage_id": pid,
                "law": p.law,
                "citation": p.citation,
                "passage": p.text,
                **item,
                "checked": verdict if rank < N_CHECK else None,
            }
        )
    return out, stats


def sources_doc(
    status: str, plan: Sequence[str], used: Sequence[str], meta: Mapping[str, Any]
) -> dict[str, Any]:
    """The machine-readable exclusion list T4.x loads.

    ``source_passage_ids`` = every planned passage (used + reserve), so the T4 test set stays
    clear of them whatever items finally survive; ``used_passage_ids`` = the final dev items.
    """
    return {
        "schema": 1,
        "status": status,
        "dev_only": True,
        "source_passage_ids": sorted(plan),
        "used_passage_ids": sorted(used),
        **meta,
    }


def load_sources(path: Path = SOURCES_PATH) -> set[str]:
    """Return ``source_passage_ids`` of the committed exclusion list (T4.x calls this)."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    return set(doc["source_passage_ids"])


def render_card(
    records: Sequence[Item], stats: Mapping[str, int], gen_model: str, check_model: str
) -> str:
    """The data card (Markdown) of the assembled set: ``CARD_TEMPLATE`` filled with the facts."""
    laws: dict[str, int] = {}
    for r in records:
        laws[r["law"]] = laws.get(r["law"], 0) + 1
    return CARD_TEMPLATE.read_text(encoding="utf-8").format(
        n=len(records),
        gen=gen_model,
        check=check_model,
        gen_prompt=GEN_PROMPT,
        check_prompt=CHECK_PROMPT,
        n_check=N_CHECK,
        checked=stats["checked"],
        dropped_check=stats["dropped_check"],
        dropped_no_item=stats["dropped_no_item"],
        seed=SEED,
        min_chars=MIN_CHARS,
        max_chars=MAX_CHARS,
        laws="\n".join(f"| {k} | {v} |" for k, v in sorted(laws.items())),
    )

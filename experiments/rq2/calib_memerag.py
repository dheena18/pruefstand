"""MEMERAG-DE faithfulness items (T5.3 set 1; CC BY-NC 4.0, download-only).

Schema at commit ``aa274f6`` (``data/sources.yaml``): one row per (question, model answer) with
``query_id``, ``query``, ``context`` (list of ``{"text"}``, the passages the annotators saw) and
``answer`` (list of sentences with ``factuality``). In ``memerag/de.jsonl`` ``factuality`` is one
label per sentence; in ``memerag_ext/de.jsonl`` it is a list of five annotator labels, reduced here
by strict majority vote. The upstream ``data/memerag_ext_w_majority_vote/de.jsonl`` (not in the
T2.1 pin) gives the same labels: 0 sentence and 0 item differences over its 150 rows (D862).
Output only ever goes to the git-ignored ``data/derived/memerag_de/``.
"""

from collections import Counter
from collections.abc import Sequence
from typing import Any

from rq2.calib_schema import CalibrationItem, make_item_id

SUPPORTED = "Supported"
NOT_SUPPORTED = "Not Supported"
CHALLENGING = "Challenging to determine"
SET_NAME = "faithfulness_memerag"


def majority(labels: Sequence[str]) -> str:
    """Return the strict-majority label of ``labels``; ``Challenging…`` when there is none."""
    label, count = Counter(labels).most_common(1)[0]
    return label if count * 2 > len(labels) else CHALLENGING


def sentence_label(factuality: str | Sequence[str]) -> str:
    """Return one sentence's label (a single label, or the majority of several annotators)."""
    return factuality if isinstance(factuality, str) else majority(list(factuality))


def answer_label(sentence_labels: Sequence[str]) -> int | None:
    """Aggregate sentence labels to the item label (T5.3 construction rule).

    Returns:
        2 iff every sentence is ``Supported``; 0 iff at least one is ``Not Supported``; ``None``
        (drop) when a ``Challenging…`` sentence occurs without a ``Not Supported`` one.
    """
    if any(lab == NOT_SUPPORTED for lab in sentence_labels):
        return 0
    if all(lab == SUPPORTED for lab in sentence_labels):
        return 2
    return None


def memerag_item(row: dict[str, Any], variant: str) -> CalibrationItem | None:
    """Turn one MEMERAG row into a faithfulness item, or ``None`` when it is dropped."""
    labels = [sentence_label(s["factuality"]) for s in row["answer"]]
    label = answer_label(labels)
    if label is None:
        return None
    passages = [str(c["text"]).strip() for c in row["context"]]
    inputs = {
        "frage": str(row["query"]).strip(),
        "kontext": "\n\n".join(f"[{i}] {p}" for i, p in enumerate(passages, 1)),
        "antwort": " ".join(str(s["sentence"]).strip() for s in row["answer"]),
    }
    cluster = "memerag:" + str(row["query_id"]).split("#", 1)[0]
    construction = f"{variant}_majority" if variant == "memerag_ext" else variant
    hard = label == 0
    return CalibrationItem(
        item_id=make_item_id(SET_NAME, cluster, construction, inputs),
        metric="faithfulness",
        cluster_id=cluster,
        inputs=inputs,
        label=label,
        source="memerag",
        construction=construction,
        hard_negative=hard,
        hard_type="memerag_not_supported" if hard else None,
    )


def build_memerag(variants: dict[str, list[dict[str, Any]]]) -> list[CalibrationItem]:
    """Build the MEMERAG set from both German files (extended majority vote first).

    An answer that occurs in both files (same question and answer text) is kept once, from the
    majority-vote file.

    Args:
        variants: ``calib_sources.load_memerag`` output.

    Returns:
        Items in input order, de-duplicated by (question, answer).
    """
    seen: set[tuple[str, str]] = set()
    items: list[CalibrationItem] = []
    for variant in ("memerag_ext", "memerag"):
        for row in variants.get(variant, []):
            item = memerag_item(row, variant)
            if item is None:
                continue
            key = (item.inputs["frage"], item.inputs["antwort"])
            if key not in seen:
                seen.add(key)
                items.append(item)
    return items

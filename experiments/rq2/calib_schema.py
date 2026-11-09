"""The calibration item of T5.3 (local to ``experiments/rq2``, not a cross-module contract).

One :class:`CalibrationItem` is one (judge input, gold label) pair. ``inputs`` holds exactly the
prompt variables of the judged metric (``pruefstand.judges.output.SPECS``, D702), so T5.4 can feed
it to the judge unchanged. Labels use the judge's raw scale: 0..2 for faithfulness and
answer_correctness, 0..1 for perturbation_consistency and refusal_judged.
"""

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

#: Highest raw label per metric (the judge's scale, D701).
MAX_LABEL: dict[str, int] = {
    "faithfulness": 2,
    "answer_correctness": 2,
    "perturbation_consistency": 1,
    "refusal_judged": 1,
}

#: Judge input fields per metric (must equal ``judges.output.SPECS[metric].variables`` as a set).
INPUT_FIELDS: dict[str, frozenset[str]] = {
    "faithfulness": frozenset({"frage", "kontext", "antwort"}),
    "answer_correctness": frozenset({"frage", "referenz", "antwort"}),
    "perturbation_consistency": frozenset({"frage", "referenz", "antwort"}),
    "refusal_judged": frozenset({"frage", "antwort"}),
}

HARD_TYPES: frozenset[str] = frozenset(
    {
        "same_paragraph_span",
        "number_date_swap",
        "negation_flip",
        "partial_answer",
        "memerag_not_supported",
        "hedged_answer",
    }
)

CalibSplit = Literal["dev", "test"]


class CalibrationItem(BaseModel):
    """One labelled judge input.

    Attributes:
        item_id: Stable id (``<set>:<16 hex>``), see :func:`make_item_id`.
        metric: Judged metric the label belongs to (a key of :data:`MAX_LABEL`).
        cluster_id: Unit of the dev/test split and of the cluster bootstrap in T5.4.
        inputs: Judge prompt variables, exactly :data:`INPUT_FIELDS` of ``metric``.
        label: Gold raw score, ``0 <= label <= MAX_LABEL[metric]``.
        source: Upstream dataset (``memerag``, ``germanquad``, ``germanrag``).
        construction: How the item was made (e.g. ``annotator_answer_2``, ``number_date_swap``).
        trivial: Candidate equals the reference after NFC casefolding (excluded from primary κ).
        hard_negative: Part of the hard-negative subset (round 8 W3.8); always ``label < max``.
        hard_type: Kind of hard negative; set iff ``hard_negative``.
        calib_split: ``dev`` or ``test`` (AI13-12); ``None`` only before the split is assigned.

    Raises:
        ValueError: (pydantic ``ValidationError``) on an unknown metric, a label out of range,
            wrong input fields, or an inconsistent hard-negative tag.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_id: str
    metric: str
    cluster_id: str
    inputs: dict[str, str]
    label: int
    source: str
    construction: str
    trivial: bool = False
    hard_negative: bool = False
    hard_type: str | None = None
    calib_split: CalibSplit | None = None

    @model_validator(mode="after")
    def _check(self) -> "CalibrationItem":
        if self.metric not in MAX_LABEL:
            msg = f"unknown metric {self.metric!r}"
            raise ValueError(msg)
        if not 0 <= self.label <= MAX_LABEL[self.metric]:
            msg = f"label {self.label} out of range for {self.metric}"
            raise ValueError(msg)
        if set(self.inputs) != INPUT_FIELDS[self.metric]:
            msg = f"inputs {sorted(self.inputs)} != {sorted(INPUT_FIELDS[self.metric])}"
            raise ValueError(msg)
        if self.hard_negative != (self.hard_type is not None):
            msg = "hard_type must be set exactly for hard negatives"
            raise ValueError(msg)
        if self.hard_type is not None and self.hard_type not in HARD_TYPES:
            msg = f"unknown hard_type {self.hard_type!r}"
            raise ValueError(msg)
        if self.hard_negative and self.label >= MAX_LABEL[self.metric]:
            msg = "a hard negative needs a label below the maximum"
            raise ValueError(msg)
        return self


def make_item_id(set_name: str, cluster_id: str, construction: str, inputs: dict[str, str]) -> str:
    """Return a stable item id from the item's content.

    Args:
        set_name: Label-set name, e.g. ``correctness``.
        cluster_id: The item's cluster.
        construction: The construction tag.
        inputs: The judge inputs.

    Returns:
        ``<set_name>:<first 16 hex of sha256>``.

    >>> make_item_id("refusal", "c1", "gold_answer", {"frage": "F", "antwort": "A"})[:8]
    'refusal:'
    """
    blob = json.dumps([cluster_id, construction, inputs], sort_keys=True, ensure_ascii=False)
    return f"{set_name}:{hashlib.sha256(blob.encode()).hexdigest()[:16]}"


def is_positive(item: CalibrationItem) -> bool:
    """Return True iff the item carries the metric's top label (binarised positive)."""
    return item.label == MAX_LABEL[item.metric]

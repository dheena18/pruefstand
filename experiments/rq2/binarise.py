"""Binarisation of judge scores and labels, and the MEMERAG routing guard (T5.4 S2, D146).

A score or label is positive iff it is the metric's top raw score ("2 vs < 2" on 3-point metrics,
the raw value on binary ones). MEMERAG content (CC BY-NC, ``data/derived/memerag_de/``) is judged
by local judges only: routing it to a ``github/...`` judge raises ``ConfigError`` before any call.
"""

from collections.abc import Sequence
from pathlib import PurePath

from pruefstand.core.errors import ConfigError
from pruefstand.judges.output import spec_of

LOCAL_PROVIDERS = ("ollama/",)
MEMERAG_DIR = "memerag_de"


def binarise(metric: str, raw: int) -> int:
    """Return 1 iff ``raw`` is the top raw score of ``metric``.

    >>> binarise("faithfulness", 2), binarise("faithfulness", 1), binarise("refusal_judged", 1)
    (1, 0, 1)
    """
    return int(raw == spec_of(metric).max_raw)


def binary_pairs(
    metric: str, scores: Sequence[int], labels: Sequence[int]
) -> list[tuple[int, int]]:
    """Pair binarised judge scores with binarised labels.

    >>> binary_pairs("answer_correctness", [2, 1, 0], [2, 0, 0])
    [(1, 1), (0, 0), (0, 0)]
    """
    return [(binarise(metric, s), binarise(metric, y)) for s, y in zip(scores, labels, strict=True)]


def is_local(judge_id: str) -> bool:
    """Whether the judge runs on the local A40 cluster (Ollama)."""
    return judge_id.startswith(LOCAL_PROVIDERS)


def check_route(judge_id: str, set_name: str, path: str, *, local_only: bool) -> None:
    """Refuse to send a local-only set (MEMERAG) to a non-local judge.

    Raises:
        ConfigError: ``local_only`` is set, the path lies under ``memerag_de`` or the set name says
            MEMERAG, and the judge is not local.
    """
    memerag = local_only or MEMERAG_DIR in PurePath(path).parts or "memerag" in set_name
    if memerag and not is_local(judge_id):
        msg = f"{set_name}: MEMERAG content is judged by local judges only, not {judge_id}"
        raise ConfigError(msg)

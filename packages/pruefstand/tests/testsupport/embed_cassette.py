"""Recorded bge-m3 embeddings of the build-test questions (T4.7a, ADR-0008).

``tests/cassettes/dataset_embed/bge_m3_questions.json`` maps each question to the vector the real
bge-m3 model returned through Ollama's native ``/api/embed`` (recorded by
``record_cassettes.sh --review`` under ``pruefstand-lock``; never written by hand). Replay raises on
a text that was not recorded.
"""

import json
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from testsupport.qa_support import REPO

PATH = REPO / "packages/pruefstand/tests/cassettes/dataset_embed/bge_m3_questions.json"
MODEL = "ollama/bge-m3"


def recorded_embedder(path: Path = PATH) -> "RecordedEmbedder":
    """Return the replaying embedder (loads the cassette once)."""
    return RecordedEmbedder(json.loads(path.read_text(encoding="utf-8")))


class RecordedEmbedder:
    """Callable ``texts -> float32 matrix`` served from recorded real embeddings."""

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors

    def __call__(self, texts: Sequence[str]) -> NDArray[np.float32]:
        missing = [t for t in texts if t not in self._vectors]
        if missing:
            msg = f"no recorded embedding for {missing[0]!r} (record_cassettes.sh --review)"
            raise AssertionError(msg)
        return np.asarray([self._vectors[t] for t in texts], dtype=np.float32)

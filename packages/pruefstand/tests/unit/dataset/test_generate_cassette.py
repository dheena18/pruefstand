"""Replay of the cassettes recorded from the REAL datagen model (``make cassettes``, dataset stage).

The cassettes in ``tests/cassettes/dataset`` come only from real GitHub Models calls made by the
owner or lead (``models.github.ai`` is not reachable from the VM, D604); until they exist these
tests are skipped, never replaced by hand-written files.
"""

import numpy as np
import pytest
from testsupport.qa_support import (
    CASSETTE_DIR,
    LIVE_CHUNKS,
    check_candidates,
    slice_chunks,
)

from pruefstand.dataset.datagen_guard import datagen_policy
from pruefstand.dataset.datagen_pins import DATAGEN_MODEL
from pruefstand.dataset.generate import GenStats, generate_qa
from pruefstand.llm.budget import Budget
from pruefstand.llm.cassettes import CassetteRecorder
from pruefstand.llm.client import LLMClient
from pruefstand.llm.recorder import CallRecorder

pytestmark = pytest.mark.skipif(
    not list(CASSETTE_DIR.glob("*.json")),
    reason="no dataset cassettes recorded yet (owner/lead [NET])",
)


async def test_recorded_answers_become_valid_candidates() -> None:
    backend = CassetteRecorder(CASSETTE_DIR, "replay").wrap(None)
    client = LLMClient(
        backend, None, Budget(0.0, None, max_requests=12), CallRecorder(), datagen_policy(None)
    )
    chunks = slice_chunks()
    stats = GenStats()
    got = await generate_qa(
        [chunks[i] for i in LIVE_CHUNKS],
        client,
        DATAGEN_MODEL,
        "qa_factual_de_v1",
        np.random.default_rng(7),
        concurrency=1,
        stats=stats,
    )
    check_candidates(list(got), chunks)

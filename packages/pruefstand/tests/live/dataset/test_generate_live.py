"""Real datagen calls (T4.2, D1201): three real chunks give three valid candidates.

The model is the pin of ``PRUEFSTAND_DATAGEN_BACKEND``: ``vm`` (default) calls the VM CPU model at
``PRUEFSTAND_JUDGE_BASE_URL`` (``scripts/models/vm_llm.sh start``), ``github`` GitHub Models.

``make cassettes`` runs this file with ``PRUEFSTAND_RECORD_DATASET=1``; the real answers are then
written to ``tests/cassettes/dataset`` through ``CassetteRecorder`` (never by hand).
"""

import os

import numpy as np
import pytest
from testsupport.qa_support import (
    CASSETTE_DIR,
    LIVE_CHUNKS,
    check_candidates,
    slice_chunks,
)

from pruefstand.core.config import ModelRef
from pruefstand.core.protocols import LLMBackend
from pruefstand.core.settings import PruefstandSettings
from pruefstand.dataset.datagen_guard import datagen_policy
from pruefstand.dataset.datagen_pins import datagen_model
from pruefstand.dataset.generate import GenStats, generate_qa
from pruefstand.llm.backends.litellm import GITHUB_MODELS_URL, LiteLLMBackend
from pruefstand.llm.budget import Budget
from pruefstand.llm.cassettes import CassetteRecorder
from pruefstand.llm.client import LLMClient
from pruefstand.llm.families import family_of
from pruefstand.llm.policy import provider_of
from pruefstand.llm.recorder import CallRecorder

pytestmark = [pytest.mark.live, pytest.mark.network]
SETTINGS = PruefstandSettings()
MODEL = os.environ.get("PRUEFSTAND_DATAGEN_TEST_MODEL", datagen_model(SETTINGS.datagen_backend))
GITHUB = provider_of(MODEL) == "github"


def _backend() -> LLMBackend:
    if GITHUB:
        return LiteLLMBackend(
            MODEL,
            api_base=GITHUB_MODELS_URL,
            api_key_env="PRUEFSTAND_GH_MODELS_TOKEN",
            timeout_s=60,
        )
    return LiteLLMBackend(MODEL, api_base=SETTINGS.judge_base_url, api_key_env=None, timeout_s=600)


@pytest.mark.skipif(
    not (os.environ.get("PRUEFSTAND_GH_MODELS_TOKEN") if GITHUB else SETTINGS.judge_base_url),
    reason="needs PRUEFSTAND_GH_MODELS_TOKEN (github) or PRUEFSTAND_JUDGE_BASE_URL (VM model)",
)
async def test_three_real_chunks_give_three_valid_candidates() -> None:
    ModelRef(id=MODEL, family=family_of(MODEL))
    backend = _backend()
    if os.environ.get("PRUEFSTAND_RECORD_DATASET") == "1":
        backend = CassetteRecorder(CASSETTE_DIR, "record").wrap(backend)
    client = LLMClient(
        backend,
        None,
        Budget(0.0, None, max_requests=12),
        CallRecorder(),
        datagen_policy(None, provider_of(MODEL)),
    )
    chunks = slice_chunks()
    stats = GenStats()
    got = await generate_qa(
        [chunks[i] for i in LIVE_CHUNKS],
        client,
        MODEL,
        "qa_factual_de_v1",
        np.random.default_rng(7),
        concurrency=1,
        stats=stats,
    )
    check_candidates(list(got), chunks)

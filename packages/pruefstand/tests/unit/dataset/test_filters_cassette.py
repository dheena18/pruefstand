"""Replay of support-check cassettes recorded from the REAL support model (T4.3).

The cassettes in ``tests/cassettes/dataset/support`` come only from real GitHub Models calls made
by the owner or lead (``make cassettes``, dataset stage; ``models.github.ai`` is not reachable from
the VM, D604); until they exist these tests are skipped, never replaced by hand-written files.
"""

import pytest
from testsupport.filters_support import ANSWER, QUESTION, SUPPORT_MODEL
from testsupport.qa_support import CASSETTE_DIR, chunk

from pruefstand.core.ids import ChunkId
from pruefstand.core.models.dataset import QACandidate
from pruefstand.dataset.datagen_guard import datagen_policy
from pruefstand.dataset.filters import check_support
from pruefstand.llm.budget import Budget
from pruefstand.llm.cassettes import CassetteRecorder
from pruefstand.llm.client import LLMClient
from pruefstand.llm.recorder import CallRecorder

SUPPORT_DIR = CASSETTE_DIR / "support"
pytestmark = pytest.mark.skipif(
    not list(SUPPORT_DIR.glob("*.json")),
    reason="no support cassettes recorded yet (owner/lead [NET])",
)


def _client() -> LLMClient:
    backend = CassetteRecorder(SUPPORT_DIR, "replay").wrap(None)
    return LLMClient(
        backend, None, Budget(0.0, None, max_requests=4), CallRecorder(), datagen_policy(None)
    )


def _cand() -> QACandidate:
    return QACandidate(
        question=QUESTION, answer=ANSWER, citation="§ 622 Abs. 2 BGB",
        chunk_id=ChunkId("gii-bgb-622#1"), prompt_version="qa_factual_de_v1",
    )  # fmt: skip


async def test_the_recorded_support_model_keeps_a_supported_answer() -> None:
    result = await check_support(_cand(), chunk("gii-bgb-622#1"), _client(), SUPPORT_MODEL)
    assert result.kept


async def test_the_recorded_support_model_rejects_the_wrong_chunk() -> None:
    result = await check_support(_cand(), chunk("gii-arbzg-3#0"), _client(), SUPPORT_MODEL)
    assert result.reasons == ("unsupported",)

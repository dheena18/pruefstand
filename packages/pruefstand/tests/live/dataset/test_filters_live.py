"""Real models behind the T4.3 filters: the embedding server and the support model.

``make cassettes`` runs the support test with ``PRUEFSTAND_RECORD_SUPPORT=1``; the real answers are
then written to ``tests/cassettes/dataset/support`` through ``CassetteRecorder`` (never by hand).
The embedding test needs ``PRUEFSTAND_EMBED_URL`` (the tier-1 CPU embedding server, BGE-M3).
"""

import os

import pytest
from filter_qa_embed import make_embedder
from testsupport.filters_support import ANSWER, PARAPHRASES, QUESTION, SUPPORT_MODEL
from testsupport.qa_support import CASSETTE_DIR, DATAGEN, chunk

from pruefstand.core.ids import ChunkId
from pruefstand.core.models.dataset import QACandidate
from pruefstand.core.protocols import LLMBackend
from pruefstand.dataset.datagen_guard import datagen_policy
from pruefstand.dataset.filters import check_support, dedupe
from pruefstand.llm.backends.litellm import GITHUB_MODELS_URL, LiteLLMBackend
from pruefstand.llm.budget import Budget
from pruefstand.llm.cassettes import CassetteRecorder
from pruefstand.llm.client import LLMClient
from pruefstand.llm.recorder import CallRecorder

pytestmark = pytest.mark.live


def _cand(question: str, chunk_id: str = "gii-bgb-622#1") -> QACandidate:
    return QACandidate(
        question=question, answer=ANSWER, citation=None, chunk_id=ChunkId(chunk_id),
        prompt_version="qa_factual_de_v1",
    )  # fmt: skip


@pytest.mark.skipif(
    not os.environ.get("PRUEFSTAND_EMBED_URL"), reason="PRUEFSTAND_EMBED_URL is not set"
)
def test_the_real_embedding_model_finds_the_paraphrase() -> None:
    embed = make_embedder(os.environ["PRUEFSTAND_EMBED_URL"], "tei", "bge-m3")
    kept = dedupe([_cand(q) for q in PARAPHRASES], embed, 0.9)
    assert len(kept) == 2
    assert PARAPHRASES[2] in {c.question for c in kept}
    assert len({c.question for c in kept} & set(PARAPHRASES[:2])) == 1


@pytest.mark.network
@pytest.mark.skipif(
    not os.environ.get("PRUEFSTAND_GH_MODELS_TOKEN"),
    reason="PRUEFSTAND_GH_MODELS_TOKEN is not set (fork PRs and offline runs have no token)",
)
async def test_the_real_support_model_tells_the_right_chunk_from_the_wrong_one() -> None:
    backend: LLMBackend = LiteLLMBackend(
        SUPPORT_MODEL, api_base=GITHUB_MODELS_URL, api_key_env="PRUEFSTAND_GH_MODELS_TOKEN",
        timeout_s=60,
    )  # fmt: skip
    if os.environ.get("PRUEFSTAND_RECORD_SUPPORT") == "1":
        backend = CassetteRecorder(CASSETTE_DIR / "support", "record").wrap(backend)
    client = LLMClient(
        backend, None, Budget(0.0, None, max_requests=6), CallRecorder(), datagen_policy(None)
    )
    right = await check_support(
        _cand(QUESTION), chunk("gii-bgb-622#1"), client, SUPPORT_MODEL, generator_model=DATAGEN
    )
    wrong = await check_support(
        _cand(QUESTION), chunk("gii-arbzg-3#0"), client, SUPPORT_MODEL, generator_model=DATAGEN
    )
    assert right.kept
    assert wrong.reasons == ("unsupported",)

"""Records real bge-m3 embeddings of the build-test questions (T4.7a, ADR-0008).

Run by ``record_cassettes.sh --review`` on the VM under the GPU lock. Without
``PRUEFSTAND_RECORD_REVIEW=1`` it is skipped. The vectors come from the real model, never by hand.
"""

import json
import os

import pytest
from testsupport.build_support import QA
from testsupport.embed_cassette import MODEL, PATH

from pruefstand.llm.providers import ollama_base_url
from pruefstand.pipeline.build_clients import make_embedder

pytestmark = [
    pytest.mark.live,
    pytest.mark.gpu,
    pytest.mark.skipif(
        os.environ.get("PRUEFSTAND_RECORD_REVIEW") != "1",
        reason="set PRUEFSTAND_RECORD_REVIEW=1 (scripts/models/record_cassettes.sh --review)",
    ),
]


def test_record_the_question_embeddings() -> None:
    embed = make_embedder(ollama_base_url(MODEL), "ollama", "bge-m3")
    questions = [q for _, q, _ in QA]
    matrix = embed(questions)
    assert matrix.shape[0] == len(questions)
    assert matrix.shape[1] >= 256
    PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {q: [round(float(x), 6) for x in row] for q, row in zip(questions, matrix, strict=True)}
    PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

"""``LLMRequest.json_schema`` and ``complete_json_meta`` (T5.2a, interface addition)."""

from pathlib import Path

import pytest
from pydantic import BaseModel
from testsupport.judge_support import MODEL, TAGS, configure, make_client
from testsupport.llm_scenarios import DictCache, echo_request
from testsupport.loopback_script import Step, ollama_body, serve_script

from pruefstand.core.models.llm import LLMRequest
from pruefstand.llm.backends.kwargs import completion_kwargs
from pruefstand.llm.client import cache_key

SCHEMA: dict[str, object] = {"type": "object", "properties": {"score": {"type": "integer"}}}


class Out(BaseModel):
    score: int


def _req(model: str, **update: object) -> LLMRequest:
    return echo_request().model_copy(update={"model": model, "response_format": "json", **update})


def test_an_ollama_request_with_a_schema_sends_it_as_the_response_schema() -> None:
    options = {"num_ctx": 1, "num_predict": 2, "temperature": 0.0, "seed": 1, "top_p": 1.0}
    kwargs = completion_kwargs(
        _req("ollama/x:1", json_schema=SCHEMA),
        api_base="http://127.0.0.1:1",
        api_key="k",
        timeout_s=1,
        options=options,
    )
    assert kwargs["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "echo", "schema": SCHEMA},
    }


def test_other_providers_and_requests_without_a_schema_stay_in_json_mode() -> None:
    plain = completion_kwargs(
        _req("openai_compatible_local/m", json_schema=SCHEMA),
        api_base=None,
        api_key="k",
        timeout_s=1,
    )
    assert plain["response_format"] == {"type": "json_object"}


def test_the_schema_is_part_of_the_cache_key_and_absent_means_the_old_key() -> None:
    base = _req(MODEL)
    with_schema = base.model_copy(update={"json_schema": SCHEMA})
    other = base.model_copy(update={"json_schema": {"type": "object"}})
    assert len({cache_key(base), cache_key(with_schema), cache_key(other)}) == 3
    assert "json_schema" not in base.model_dump(mode="json")  # earlier cassette hashes hold


async def test_complete_json_meta_returns_the_response_and_the_cache_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = DictCache()
    with serve_script([Step(body=ollama_body('{"score": 3}'))], tags=TAGS) as (origin, state):
        configure(tmp_path, monkeypatch, origin)
        client, _ = make_client(cache)
        req = _req(MODEL, json_schema=SCHEMA)
        first, resp1 = await client.complete_json_meta(req, Out)
        second, resp2 = await client.complete_json_meta(req, Out)
        assert state.posts() == 1
    assert (first.score, second.score) == (3, 3)
    assert (resp1.cached, resp2.cached) == (False, True)

"""``num_ctx`` goes out with every judge request, whatever the caller asked (T5.2c, D1011)."""

import json
from pathlib import Path

import pytest
from testsupport.gpu_files import OPTIONS
from testsupport.judge_support import MODEL, TAGS, configure, make_judge
from testsupport.loopback_script import Step, ollama_body, serve_script

from pruefstand.core.models.llm import LLMRequest, LLMRole, Message
from pruefstand.judges.output import make_task
from pruefstand.llm.backends.kwargs import completion_kwargs
from pruefstand.llm.providers import catalogue_options

ANSWER = {"frage": "F?", "referenz": "R.", "antwort": "A."}


def posted_options(state: object) -> list[dict[str, object]]:
    seen = getattr(state, "seen")  # noqa: B009  (ScriptState, typed loosely here)
    return [p.body["options"] for p in seen if p.method == "POST" and p.path != "/api/show"]


async def test_a_plain_judge_call_sends_the_catalogue_num_ctx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = json.dumps({"reason": "x", "score": 1})
    with serve_script([Step(body=ollama_body(good))], tags=TAGS) as (origin, state):
        configure(tmp_path, monkeypatch, origin)
        judge, _ = make_judge()
        await judge.score(make_task("answer_correctness", **ANSWER))
    (options,) = posted_options(state)
    assert options["num_ctx"] == OPTIONS["num_ctx"]


async def test_the_json_repair_retry_sends_it_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = json.dumps({"reason": "x", "score": 1})
    steps = [Step(body=ollama_body("kein JSON")), Step(body=ollama_body(good))]
    with serve_script(steps, tags=TAGS) as (origin, state):
        configure(tmp_path, monkeypatch, origin)
        judge, _ = make_judge()
        await judge.score(make_task("answer_correctness", **ANSWER))
    first, repair = posted_options(state)
    assert first["num_ctx"] == repair["num_ctx"] == OPTIONS["num_ctx"]


@pytest.mark.parametrize("max_tokens", [1, 384, 4096, 16_384])  # incl. the doubled repair budget
def test_no_request_shape_can_change_num_ctx(
    max_tokens: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(tmp_path, monkeypatch, "http://127.0.0.1:1")
    request = LLMRequest(
        role=LLMRole.JUDGE,
        model=MODEL,
        messages=(Message(role="user", content="x"),),
        max_tokens=max_tokens,
        prompt_id="p",
        prompt_version="v1",
    )
    kwargs = completion_kwargs(
        request, api_base="http://x", api_key="k", timeout_s=1.0, options=catalogue_options(MODEL)
    )
    assert kwargs["num_ctx"] == int(OPTIONS["num_ctx"])

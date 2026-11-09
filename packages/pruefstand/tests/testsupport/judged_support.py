"""Helpers for the judged-metric tests: a real ``Judge`` over a scripted loopback Ollama."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from testsupport.judge_support import MODEL, TAGS, configure, make_judge
from testsupport.loopback_script import ScriptState, Step, ollama_body, serve_script

from pruefstand.core.ids import ChunkId, DocId
from pruefstand.core.models.target import RetrievedChunk, TargetResponse
from pruefstand.judges.judge import JudgePool
from pruefstand.llm.recorder import CallRecorder

CAP = 4096 - 1024  # the loopback catalogue has num_ctx 4096 (testsupport.gpu_files.OPTIONS)


def verdict(raw: int) -> Step:
    """A scripted judge answer with raw score ``raw``."""
    return Step(body=ollama_body(json.dumps({"reason": "begründet", "score": raw})))


def failing(status: int = 503) -> Step:
    """A scripted server error."""
    return Step(status=status)


@contextmanager
def judges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, steps: list[Step]
) -> Iterator[tuple[JudgePool, ScriptState, CallRecorder]]:
    """A one-judge pool whose model answers ``steps`` in order (then with invalid JSON)."""
    with serve_script(steps, tags=TAGS) as (origin, state):
        configure(tmp_path, monkeypatch, origin)
        judge, recorder = make_judge()
        assert judge.model == MODEL
        yield JudgePool({"default": judge}, "default"), state, recorder


def user_prompts(state: ScriptState) -> list[str]:
    """The user message of every judge request the server saw."""
    out: list[str] = []
    for seen in state.seen:
        messages: Any = seen.body.get("messages")
        if seen.path != "/api/show" and isinstance(messages, list):
            out.append(str(messages[-1]["content"]))
    return out


def chunk(index: int, *, used: bool | None = None, text: str | None = None) -> RetrievedChunk:
    """Chunk ``c<index>`` with rank ``index``; its text is ``Absatz <index> ...`` by default."""
    return RetrievedChunk(
        chunk_id=ChunkId(f"c{index}"),
        doc_id=DocId("bgb-622"),
        text=text if text is not None else f"Absatz {index}: Die Frist beträgt vier Wochen.",
        score=1.0 - index / 100,
        rank=index,
        used_in_prompt=used,
    )


def response(answer: str = "Vier Wochen.", **fields: Any) -> TargetResponse:
    """A target response."""
    return TargetResponse(answer=answer, **fields)

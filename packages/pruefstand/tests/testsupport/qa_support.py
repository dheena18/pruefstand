"""Builders for the QA generation tests (T4.2): real corpus chunks and a scripted datagen server.

The chunks are the real law texts of ``corpus/slice_v1``. The datagen "model" is the scripted
loopback server of ``loopback_script`` (real sockets, no model): it only shows that requests,
retries, caching and the stop rules of the real ``LLMClient`` work; no answer text is recorded
from a model here (real recordings are made by ``make cassettes``, ``record_cassettes.sh``).
"""

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from testsupport.llm_scenarios import DictCache
from testsupport.loopback_script import ScriptState, Step, serve_script

from pruefstand.core.config import ModelRef
from pruefstand.core.models.attacks import CanaryRegistry
from pruefstand.core.models.corpus import Chunk
from pruefstand.dataset.datagen_guard import datagen_policy
from pruefstand.llm.backends.litellm import LiteLLMBackend
from pruefstand.llm.budget import Budget
from pruefstand.llm.client import LLMClient
from pruefstand.llm.recorder import CallRecorder
from pruefstand.llm.retry import RetryPolicy

REPO = Path(__file__).resolve().parents[4]
SLICE = REPO / "corpus" / "slice_v1"
DATAGEN = "github/openai/gpt-4.1-mini"
SECOND = "github/meta/llama-3.3-70b-instruct"
KEY_ENV = "PRUEFSTAND_TEST_DATAGEN_KEY"

FACTUAL_ANSWER = {
    "question": (
        "Wie lange muss mein Arbeitgeber mir vorher kündigen, wenn ich zwei Jahre dort arbeite?"
    ),
    "answer": "Einen Monat zum Ende eines Kalendermonats.",
    "citation": "§ 622 Abs. 2 Nr. 1 BGB",
    "evidence": "1. zwei Jahre bestanden hat, einen Monat zum Ende eines Kalendermonats,",
    "style": "laie",
}


def slice_chunks() -> dict[str, Chunk]:
    """Every chunk of the slice corpus by ``chunk_id``."""
    out: dict[str, Chunk] = {}
    for path in sorted(SLICE.glob("*.chunks.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            chunk_ = Chunk.model_validate_json(line)
            out[chunk_.chunk_id] = chunk_
    return out


def chunk(chunk_id: str) -> Chunk:
    """One real chunk of the slice corpus."""
    return slice_chunks()[chunk_id]


def as_chunk(base: Chunk, **changes: object) -> Chunk:
    """``base`` with some fields replaced."""
    return base.model_copy(update=changes)


def reply(**fields: object) -> str:
    """A datagen answer as the JSON text a model would return (``FACTUAL_ANSWER`` + overrides)."""
    return json.dumps({**FACTUAL_ANSWER, **fields}, ensure_ascii=False)


def make_client(
    base: str,
    *,
    model: str = DATAGEN,
    cache: DictCache | None = None,
    max_requests: int | None = None,
    canaries: CanaryRegistry | None = None,
    max_retries: int = 0,
) -> tuple[LLMClient, CallRecorder]:
    """A real ``LLMClient`` on the real backend, pointed at the loopback server."""
    backend = LiteLLMBackend(model, api_base=f"{base}/v1", api_key_env=KEY_ENV, timeout_s=30)
    recorder = CallRecorder()
    client = LLMClient(
        backend,
        cache,
        Budget(max_usd=0.0, max_tokens=None, max_requests=max_requests),
        recorder,
        datagen_policy(canaries),
        retry=RetryPolicy(max_retries=max_retries, base_s=0.1, cap_s=0.2, jitter=0.0),
    )
    return client, recorder


@contextmanager
def datagen_server(
    content: str | None = None, steps: list[Step] | None = None
) -> Iterator[tuple[str, ScriptState]]:
    """Serve ``content`` (default: the factual answer) for every request after ``steps``."""
    with serve_script(steps, content=content if content is not None else reply()) as served:
        yield served


def sent_text(state: ScriptState, index: int = 0) -> str:
    """All message contents of the ``index``-th POST, joined."""
    posts = [s for s in state.seen if s.method == "POST"]
    messages = posts[index].body["messages"]
    assert isinstance(messages, list)
    return "\n".join(str(m["content"]) for m in messages)


def client_factory(
    base: str, calls: list[str], *, cache: DictCache | None = None
) -> Callable[[ModelRef, int | None, CallRecorder], LLMClient]:
    """A client factory for ``scripts/generate_qa.py`` that serves from the loopback server."""

    def make(ref: ModelRef, max_requests: int | None, recorder: CallRecorder) -> LLMClient:
        calls.append(ref.id)
        backend = LiteLLMBackend(ref.id, api_base=f"{base}/v1", api_key_env=KEY_ENV, timeout_s=30)
        return LLMClient(
            backend,
            cache,
            Budget(max_usd=0.0, max_tokens=None, max_requests=max_requests),
            recorder,
            datagen_policy(None),
            retry=RetryPolicy(max_retries=0, base_s=0.1, cap_s=0.2, jitter=0.0),
        )

    return make


CASSETTE_DIR = REPO / "packages" / "pruefstand" / "tests" / "cassettes" / "dataset"
LIVE_CHUNKS = ("gii-bgb-622#1", "gii-kschg-1#1", "eurlex-32016r0679-art-6-de#0")
_GERMAN_WORDS = frozenset(
    [
        "der",
        "die",
        "das",
        "den",
        "dem",
        "des",
        "ein",
        "eine",
        "einen",
        "wie",
        "was",
        "wann",
        "wer",
        "welche",
        "wird",
        "ist",
        "sind",
        "muss",
        "darf",
        "kann",
        "ich",
        "mein",
        "meine",
        "mir",
        "mich",
        "wenn",
        "für",
        "von",
        "zu",
        "im",
        "in",
        "und",
        "oder",
        "bei",
        "nach",
    ]
)


def check_candidates(candidates: list[object], chunks: dict[str, Chunk]) -> None:
    """Assert the shape the T4.2 live and replay tests demand of real datagen answers."""
    from pruefstand.core.citations import extract_citations, parse_one  # noqa: PLC0415
    from pruefstand.core.models.dataset import QACandidate  # noqa: PLC0415

    assert len(candidates) == len(LIVE_CHUNKS)
    for cand in candidates:
        assert isinstance(cand, QACandidate)
        words = cand.question.split()
        assert 3 <= len(words) <= 30
        assert _GERMAN_WORDS & {w.strip("?,.").lower() for w in words}
        key = parse_one(chunks[cand.chunk_id].citation_key or "")
        assert key is not None
        found = {(c.kind, c.number, c.law) for c in extract_citations(cand.citation or "")}
        assert (key.kind, key.number, key.law) in found

"""Shared LLM test scenarios: the same requests are recorded (live) and replayed (unit).

The requests are real inputs for the pinned test model (``infra/models/test-models.yaml``); the
module also holds a plain in-memory ``KVCache`` (a dict, not a model stand-in).
"""

from pathlib import Path

from pruefstand.core.models.llm import LLMRequest, LLMRole
from pruefstand.llm.prompts import PromptRegistry

TEST_MODEL = "openai_compatible_local/qwen2.5-0.5b-instruct"
TEST_API_BASE = "http://localhost:8080/v1"
CASSETTE_DIR = Path(__file__).resolve().parents[1] / "cassettes" / "llm"
BACKEND_CASSETTE_DIR = CASSETTE_DIR / "backend"
SENTENCE = "Die Kündigung muss schriftlich erfolgen."


class DictCache:
    """In-memory ``KVCache`` used by the client tests."""

    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    def set(self, key: str, value: bytes) -> None:
        self.data[key] = value


def echo_request(
    word: str = "Müller", *, temperature: float = 0.0, max_tokens: int = 16, seed: int | None = 0
) -> LLMRequest:
    """Request of the ``echo_v1`` prompt."""
    messages = PromptRegistry().get("echo", "v1").render(word=word)
    return LLMRequest(
        role=LLMRole.JUDGE,
        model=TEST_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        seed=seed,
        prompt_id="echo",
        prompt_version="v1",
    )


def json_probe_request(*, max_tokens: int, response_format: str = "json") -> LLMRequest:
    """Request of the ``json_probe_v1`` prompt about ``SENTENCE``."""
    messages = PromptRegistry().get("json_probe", "v1").render(sentence=SENTENCE)
    return LLMRequest(
        role=LLMRole.JUDGE,
        model=TEST_MODEL,
        messages=messages,
        max_tokens=max_tokens,
        prompt_id="json_probe",
        prompt_version="v1",
        response_format="json" if response_format == "json" else "text",
    )

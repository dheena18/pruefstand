"""Cassette client of the private-document generator tests (T2.6a).

The recorded answers in ``tests/cassettes/private_docs/`` are REAL answers of the local judge model
(``ollama/gemma3:12b``, day set), written by ``scripts/models/record_cassettes.sh --private-docs``
through the script's own ``main``; nothing in them is written by hand.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Literal

import pytest
from testsupport.qa_support import REPO

from pruefstand.core.config import LLMPolicyConfig, ModelRef
from pruefstand.core.protocols import LLMBackend
from pruefstand.llm.cassettes import CassetteRecorder

CASSETTES = REPO / "packages" / "pruefstand" / "tests" / "cassettes" / "private_docs"
ARGS = ("--tenant", "all", "--n", "2", "--seed", "7")
Builder = Callable[..., LLMBackend]


def route_backend(
    monkeypatch: pytest.MonkeyPatch, mode: Literal["record", "replay"], real: Builder | None
) -> None:
    """Make the script's ``build_backend`` record ``real`` answers or replay the cassettes."""
    import generate_private_docs as script  # noqa: PLC0415  (script on the test pythonpath)

    recorder = CassetteRecorder(CASSETTES, mode)

    def build(ref: ModelRef, *, policy: LLMPolicyConfig) -> LLMBackend:
        return recorder.wrap(real(ref, policy=policy) if real else None)

    monkeypatch.setattr(script, "build_backend", build)


def recorded() -> bool:
    """True when the committed cassettes exist."""
    return CASSETTES.is_dir() and any(CASSETTES.glob("*.json"))


def draft_dir(base: Path) -> Path:
    """The drafts directory used by the tests under ``base``."""
    return base / "drafts"

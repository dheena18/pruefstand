"""Backend-level cassettes: real ``(LLMRequest, LLMResponse)`` pairs, one JSON file each."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from pruefstand.core.errors import LLMError
from pruefstand.core.hashing import stable_hash
from pruefstand.core.models.llm import LLMRequest, LLMResponse
from pruefstand.core.protocols import LLMBackend


class CassetteFile(BaseModel):
    """Content of one cassette file; no headers and no keys, only the two models."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    recorded_at: str
    model_id: str
    model_version: str | None
    request: LLMRequest
    response: LLMResponse


class CassetteRecorder:
    """Records real backend answers (``record``) or serves them back (``replay``).

    Cassettes come only from real models through ``make cassettes``; a replay of a request that
    was never recorded raises, it never makes up an answer.

    Args:
        dir: Cassette directory (``<dir>/<stable_hash(request)>.json``).
        mode: ``"record"`` wraps a real backend, ``"replay"`` serves stored pairs.
    """

    def __init__(self, dir: Path, mode: Literal["record", "replay"]) -> None:  # noqa: A002
        self._dir = dir
        self._mode = mode

    def wrap(self, backend: LLMBackend | None) -> LLMBackend:
        """Return the recording or replaying backend.

        Args:
            backend: The real backend; required in record mode, ignored in replay mode.

        Returns:
            An ``LLMBackend``.

        Raises:
            ValueError: Record mode without a backend.
        """
        if self._mode == "replay":
            return _ReplayBackend(self._dir)
        if backend is None:
            msg = "record mode needs a real backend to wrap"
            raise ValueError(msg)
        return _RecordingBackend(self._dir, backend)


class _RecordingBackend:
    def __init__(self, directory: Path, inner: LLMBackend) -> None:
        self._dir = directory
        self._inner = inner

    async def acomplete(self, req: LLMRequest) -> LLMResponse:
        resp = await self._inner.acomplete(req)
        entry = CassetteFile(
            recorded_at=datetime.now(UTC).isoformat(timespec="seconds"),
            model_id=req.model,
            model_version=resp.model_version,
            request=req,
            response=resp,
        )
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{stable_hash(req)}.json"
        text = json.dumps(entry.model_dump(mode="json"), ensure_ascii=False, indent=2)
        path.write_text(text + "\n", encoding="utf-8")
        return resp


class _ReplayBackend:
    def __init__(self, directory: Path) -> None:
        self._dir = directory

    async def acomplete(self, req: LLMRequest) -> LLMResponse:
        key = stable_hash(req)
        path = self._dir / f"{key}.json"
        if not path.is_file():
            msg = f"cassette miss: {key} (no cassette for {req.prompt_id})"
            raise LLMError(msg, transient=False)
        entry = CassetteFile.model_validate_json(path.read_text(encoding="utf-8"))
        return entry.response.model_copy(update={"cached": False})

"""GitHub Models client with a resumable disk cache (T3.1b S4, ADR-0019).

Credential: ``PRUEFSTAND_GH_MODELS_TOKEN`` (Models: read; never ``GITHUB_TOKEN``), read from the
environment or from ``--env-file`` (only that one variable), never printed or stored. Every model
answer is cached under ``data/raw/indomain_dev_cache`` (git-ignored), so a run is resumable across
days; a 429 raises ``QuotaStop``. Used by ``indomain_cli.py`` (public law text only).
"""

import hashlib
import json
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
from model_selection import indomain_data as data

CACHE = data.REPO / "data" / "raw" / "indomain_dev_cache"
ENDPOINT = "https://models.github.ai/inference/chat/completions"
TOKEN_VAR = "PRUEFSTAND_GH_MODELS_TOKEN"  # noqa: S105  # reason: the variable NAME, not a secret


class GenError(RuntimeError):
    """A GitHub Models call failed or did not answer JSON."""


class QuotaStop(GenError):  # noqa: N818  # reason: a controlled stop, not an error condition
    """HTTP 429: the free-tier quota is used up; resume later (``retry_after`` seconds)."""

    def __init__(self, retry_after: str | None) -> None:
        super().__init__(f"quota exhausted (retry after {retry_after or 'unknown'} s)")


def read_token(env: Mapping[str, str], env_file: Path | None = None) -> str:
    """The Models token from ``env`` or the single ``TOKEN_VAR=`` line of ``env_file``."""
    if env.get(TOKEN_VAR):
        return env[TOKEN_VAR]
    if env_file is not None and env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith(TOKEN_VAR + "="):
                return line.split("=", 1)[1].strip().strip("\"'")
    msg = f"set {TOKEN_VAR} (Models: read) in the environment or pass --env-file"
    raise GenError(msg)


def parse_json_object(text: str) -> dict[str, Any]:
    """The first JSON object in ``text`` (code fences tolerated); ``GenError`` if there is none."""
    start = text.find("{")
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:]) if start >= 0 else (None, 0)
    except ValueError:
        obj = None
    if not isinstance(obj, dict):
        msg = "model answer holds no JSON object"
        raise GenError(msg)
    return obj


def cache_key(model: str, prompt: str, passage_id: str) -> str:
    """Stable file stem of one (model, prompt version, passage) call."""
    return hashlib.sha256(f"{model}|{prompt}|{passage_id}".encode()).hexdigest()[:24]


def _post(token: str, body: dict[str, Any], timeout_s: float) -> httpx.Response:
    """POST with up to two retries on HTTP 5xx; 429 raises ``QuotaStop``."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    resp: httpx.Response | None = None
    for attempt in range(3):
        try:
            resp = httpx.post(ENDPOINT, headers=headers, json=body, timeout=timeout_s)
        except httpx.HTTPError as exc:
            msg = f"request failed: {type(exc).__name__}"
            raise GenError(msg) from exc
        if resp.status_code == 429:
            raise QuotaStop(resp.headers.get("retry-after"))
        if resp.status_code < 500:
            return resp
        time.sleep(5 * (attempt + 1))
    assert resp is not None  # noqa: S101  # reason: the loop ran at least once
    return resp


def call_model(token: str, model: str, content: str, timeout_s: float = 90.0) -> str:
    """One GitHub Models chat call (temperature 0); returns the answer text."""
    body = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
        "max_tokens": 700,
    }
    resp = _post(token, body, timeout_s)
    kind = resp.headers.get("content-type", "?")
    if resp.status_code != 200 or "json" not in kind:
        msg = f"GitHub Models answered HTTP {resp.status_code} ({kind}); is the endpoint reachable?"
        raise GenError(msg)
    return str(resp.json()["choices"][0]["message"]["content"])


def cache_path(model: str, prompt: str, passage_id: str) -> Path:
    """File of one (model, prompt version, passage) answer."""
    return CACHE / f"{cache_key(model, prompt, passage_id)}.json"


def cached_response(model: str, prompt: str, passage_id: str) -> str | None:
    """The stored raw answer text, or ``None`` when the call was never made."""
    path = cache_path(model, prompt, passage_id)
    if not path.is_file():
        return None
    return str(json.loads(path.read_text(encoding="utf-8"))["response"])


def ask(token: str, model: str, prompt: str, passage_id: str, content: str) -> str:
    """One new call; the raw answer is stored (no secrets) before it is returned."""
    text = call_model(token, model, content)
    CACHE.mkdir(parents=True, exist_ok=True)
    rec = {"model": model, "prompt": prompt, "passage_id": passage_id, "response": text}
    cache_path(model, prompt, passage_id).write_text(
        json.dumps(rec, ensure_ascii=False), encoding="utf-8"
    )
    return text

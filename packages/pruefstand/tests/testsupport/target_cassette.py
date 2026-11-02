"""Replay of exchanges recorded from the REAL rag-demo (T1.10 S9, ADR-0008).

A cassette directory under ``tests/cassettes/target/<name>/`` holds ``info.yaml`` (the ``GET /v1/info``
answer) and ``query.yaml`` (every ``POST /v1/query`` exchange, keyed by tenant and question).
``scripts/live/record_target.py`` writes them from a running target; nothing is edited by hand.
Replay goes through the real ``HttpTargetAdapter`` under ``respx``; a request that was never recorded
is answered with HTTP 404 and listed in ``misses`` so a test can assert there was none.
"""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
import respx
import yaml

CASSETTES = Path(__file__).resolve().parents[1] / "cassettes" / "target"


class TargetCassette:
    """One recorded target: ``info`` and the query exchanges.

    Args:
        name: Directory name under ``tests/cassettes/target`` (``good``, ``bug_tenant``, ...).
        info_overrides: Fields of ``/v1/info`` to replace on replay (e.g. ``corpus_version``).
    """

    def __init__(self, name: str, *, info_overrides: Mapping[str, Any] | None = None) -> None:
        directory = CASSETTES / name
        info = yaml.safe_load((directory / "info.yaml").read_text(encoding="utf-8"))
        query = yaml.safe_load((directory / "query.yaml").read_text(encoding="utf-8"))
        self.info: dict[str, Any] = {**info["response"]["body"], **(info_overrides or {})}
        self._answers: dict[tuple[str, str], dict[str, Any]] = {
            (e["request"]["tenant_id"], e["request"]["question"]): e["response"]
            for e in query["exchanges"]
        }
        self.query_requests = 0
        self.misses: list[str] = []

    def install(self, router: respx.MockRouter, base: str = "") -> None:
        """Register ``/v1/info``, ``/v1/query`` and a 404 ``/v1/retrieve`` under ``base``.

        Args:
            router: The respx router.
            base: URL prefix such as ``http://localhost:8000``; empty when the router has a base URL.
        """
        router.get(f"{base}/v1/info").mock(return_value=httpx.Response(200, json=self.info))
        router.post(f"{base}/v1/query").mock(side_effect=self._answer)
        router.post(f"{base}/v1/retrieve").mock(return_value=httpx.Response(404))

    def _answer(self, request: httpx.Request) -> httpx.Response:
        self.query_requests += 1
        body = json.loads(request.content)
        found = self._answers.get((body["tenant_id"], body["question"]))
        if found is None:
            self.misses.append(f"{body['tenant_id']}: {body['question']}")
            return httpx.Response(404, json={"detail": "not recorded"})
        return httpx.Response(int(found["status"]), json=found["body"])

"""Shared index chunks_active (T3.4, D1098, D1030): idempotent check, build once, clear errors."""

import json
import threading
from collections.abc import Iterator, Mapping, Sequence
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import ClassVar

import pytest
from gate_orchestrator.gate_job import Attempt
from gate_orchestrator.gate_run import Runner
from gate_orchestrator.index_job import ALIAS, ensure_shared_index, qdrant_aliases
from gate_orchestrator.infra import InfraError
from gate_orchestrator.models import Job
from orch_testkit import SpyPoster

REPO = Path(__file__).resolve().parents[4]


class _Qdrant(BaseHTTPRequestHandler):
    """A real HTTP endpoint shaped like Qdrant's ``GET /aliases``."""

    seen_keys: ClassVar[list[str | None]] = []

    def do_GET(self) -> None:
        _Qdrant.seen_keys.append(self.headers.get("api-key"))
        body = json.dumps({"result": {"aliases": [{"alias_name": ALIAS, "collection_name": "c1"}]}})
        self.send_response(200 if self.path == "/aliases" else 404)
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002  (http.server API)
        del format, args


@pytest.fixture
def qdrant() -> Iterator[str]:
    server = HTTPServer(("127.0.0.1", 0), _Qdrant)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_aliases_are_read_with_the_read_write_key(qdrant: str) -> None:
    _Qdrant.seen_keys.clear()
    assert qdrant_aliases({"QDRANT_URL": qdrant, "QDRANT_API_KEY": "rw"}) == {ALIAS}
    assert _Qdrant.seen_keys == ["rw"]


def test_an_unreachable_qdrant_is_an_infra_error() -> None:
    with pytest.raises(InfraError, match="index_unavailable"):
        qdrant_aliases({"QDRANT_URL": "http://127.0.0.1:9"})


def _runner(calls: list[list[str]], code: int = 0) -> Runner:
    def run(argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
        calls.append(list(argv))
        return code, ""

    return run


def test_an_existing_alias_needs_no_work() -> None:
    calls: list[list[str]] = []
    assert ensure_shared_index(_runner(calls), {}, lambda env: {ALIAS}) is False
    assert calls == []


def test_a_missing_alias_is_built_once_from_the_named_corpus(tmp_path: Path) -> None:
    (tmp_path / "corpus" / "v3").mkdir(parents=True)
    states = iter([set(), {ALIAS}])
    calls: list[list[str]] = []
    env = {"PRUEFSTAND_DATA_ROOT": str(tmp_path), "PRUEFSTAND_CORPUS_VERSION": "v3"}
    assert ensure_shared_index(_runner(calls), env, lambda e: next(states)) is True
    assert calls == [
        ["rag-demo", "index", "--corpus", str(tmp_path / "corpus" / "v3"), "--encoder", "ollama"]
    ]


@pytest.mark.parametrize(
    "env",
    [{}, {"PRUEFSTAND_DATA_ROOT": "/nonexistent", "PRUEFSTAND_CORPUS_VERSION": "v3"}],
)
def test_without_a_corpus_the_error_says_what_to_set(env: dict[str, str]) -> None:
    with pytest.raises(InfraError, match="PRUEFSTAND_CORPUS_VERSION"):
        ensure_shared_index(_runner([]), env, lambda e: set())


def test_a_failed_or_incomplete_build_is_an_infra_error(tmp_path: Path) -> None:
    (tmp_path / "corpus" / "v3").mkdir(parents=True)
    env = {"PRUEFSTAND_DATA_ROOT": str(tmp_path), "PRUEFSTAND_CORPUS_VERSION": "v3"}
    with pytest.raises(InfraError, match="exit 2"):
        ensure_shared_index(_runner([], code=2), env, lambda e: set())
    with pytest.raises(InfraError, match="still missing"):
        ensure_shared_index(_runner([]), env, lambda e: set())


def test_the_attempt_checks_the_index_before_the_proxy_and_the_candidate(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def run(argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
        calls.append(list(argv))
        if list(argv[:3]) == ["docker", "image", "inspect"]:
            return 0, json.dumps({"org.opencontainers.image.revision": "a" * 40})
        return (125 if list(argv[:2]) == ["docker", "run"] else 0), ""

    attempt = Attempt(
        job=Job(kind="gate", sha="a" * 40, pr_number=7, tier="pr"),
        digest="sha256:" + "b" * 64,
        run=run,
        poster=SpyPoster(),
        statuses=lambda _sha: [],
        main_config=REPO / "pruefstand.yaml",
        work=tmp_path,
        env={},
        aliases=lambda env: set(),
    )
    with pytest.raises(InfraError, match="index_missing"):
        attempt(1)
    assert not any(c[:2] in (["docker", "compose"], ["docker", "run"]) for c in calls)

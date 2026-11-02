"""Tests for probe.sh gating of the opt-in cold-load step (T0.6 M2).

A tiny local HTTP server stands in for `/api/ps` only to observe which requests the probe makes
(a plumbing seam for the gating logic, not a model fake); `OLLAMA_URL` points the probe at it.
"""

import http.server
import json
import os
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "feasibility" / "probe.sh"


class _Handler(http.server.BaseHTTPRequestHandler):
    seen: ClassVar[list[str]] = []
    ps_body: ClassVar[bytes] = b'{"models":[]}'
    ps_status: ClassVar[int] = 200
    gen_status: ClassVar[int] = 200
    gen_body: ClassVar[bytes] = b"{}"
    gen_delay: ClassVar[float] = 0.0
    gen_drop: ClassVar[bool] = False
    loads_model: ClassVar[bool] = True
    loaded: ClassVar[bool] = False
    bodies: ClassVar[list[str]] = []

    def _reply(self, body: bytes, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # http.server API
        type(self).seen.append(f"GET {self.path}")
        if type(self).loaded:
            self._reply(b'{"models":[{"name":"qwen3.8:27b-q8_0"}]}')
        else:
            self._reply(type(self).ps_body, type(self).ps_status)

    def do_POST(self) -> None:  # http.server API
        cls = type(self)
        cls.seen.append(f"POST {self.path}")
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode()
        cls.bodies.append(raw)
        if json.loads(raw).get("keep_alive") == 0:
            cls.loaded = False
            self._reply(b"{}")
            return
        time.sleep(cls.gen_delay)
        if cls.gen_drop:
            self.close_connection = True
            return
        self._reply(cls.gen_body, cls.gen_status)
        if cls.gen_status < 300 and cls.loads_model:
            cls.loaded = True

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


@pytest.fixture
def server() -> Iterator[tuple[str, type[_Handler]]]:
    _Handler.seen = []
    _Handler.ps_body = b'{"models":[]}'
    _Handler.ps_status = 200
    _Handler.gen_status = 200
    _Handler.gen_body = b"{}"
    _Handler.gen_delay = 0.0
    _Handler.gen_drop = False
    _Handler.loads_model = True
    _Handler.loaded = False
    _Handler.bodies = []
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}", _Handler
    httpd.shutdown()


def _probe(url: str, **extra: str) -> list[str]:
    env = {k: v for k, v in os.environ.items() if k != "MEASURE_LOAD"}
    env.update({"OLLAMA_URL": url, "PROBE_CHECKS": "model-load", **extra})
    proc = subprocess.run(  # noqa: S603  # fixed argv, no shell
        ["bash", str(SCRIPT)],  # noqa: S607  # bash from PATH
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return [line for line in proc.stdout.splitlines() if line.startswith("CHECK ")]


def test_cold_load_is_skipped_by_default_without_any_request(
    server: tuple[str, type[_Handler]],
) -> None:
    url, handler = server
    lines = _probe(url)
    assert len(lines) == 1
    assert lines[0].startswith("CHECK model-load PASS SKIP")
    assert "MEASURE_LOAD=1" in lines[0]
    assert handler.seen == []


def test_measure_load_skips_when_any_model_is_loaded(server: tuple[str, type[_Handler]]) -> None:
    url, handler = server
    handler.ps_body = b'{"models":[{"name":"gemma3:12b","model":"gemma3:12b"}]}'
    lines = _probe(url, MEASURE_LOAD="1")
    assert lines[0].startswith("CHECK model-load PASS SKIP")
    assert "gemma3:12b" in lines[0]
    assert handler.seen == ["GET /api/ps"]


def test_measure_load_refuses_when_ps_is_unreadable() -> None:
    lines = _probe("http://127.0.0.1:9", MEASURE_LOAD="1")
    assert lines[0].startswith("CHECK model-load WARN")
    assert "not measuring" in lines[0]


def test_measure_load_times_the_load_when_nothing_is_loaded(
    server: tuple[str, type[_Handler]],
) -> None:
    url, handler = server
    lines = _probe(url, MEASURE_LOAD="1")
    assert lines[0].startswith("CHECK model-load PASS cold load")
    assert handler.seen == [
        "GET /api/ps",
        "POST /api/generate",
        "GET /api/ps",
        "POST /api/generate",
        "GET /api/ps",
    ]
    assert json.loads(handler.bodies[0])["keep_alive"] != 0
    assert json.loads(handler.bodies[1])["keep_alive"] == 0
    assert handler.loaded is False


def test_probe_never_prints_the_ollama_host_value() -> None:
    env = dict(os.environ)
    env.update({"PROBE_CHECKS": "ollama-store", "OLLAMA_HOST": "10.9.8.7:1234"})
    proc = subprocess.run(  # noqa: S603  # fixed argv, no shell
        ["bash", str(SCRIPT)],  # noqa: S607  # bash from PATH
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=60,
    )
    assert "10.9.8.7" not in proc.stdout


@pytest.mark.parametrize(
    ("status", "body"),
    [(500, b'{"error":"boom"}'), (200, b"{}"), (200, b'{"error":"no models key"}')],
)
def test_measure_load_refuses_on_an_unusable_ps_answer(
    server: tuple[str, type[_Handler]], status: int, body: bytes
) -> None:
    url, handler = server
    handler.ps_status = status
    handler.ps_body = body
    lines = _probe(url, MEASURE_LOAD="1")
    assert lines[0].startswith("CHECK model-load WARN")
    assert "not measuring" in lines[0]
    assert "POST /api/generate" not in handler.seen


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (500, b'{"error":"server exploded"}', "server exploded"),
        (404, b'{"error":"model not found"}', "model not found"),
        (200, b'{"error":"unable to allocate memory"}', "unable to allocate memory"),
    ],
)
def test_measure_load_fails_on_a_bad_load_answer(
    server: tuple[str, type[_Handler]], status: int, body: bytes, expected: str
) -> None:
    url, handler = server
    handler.gen_status = status
    handler.gen_body = body
    handler.loads_model = False
    lines = _probe(url, MEASURE_LOAD="1")
    assert lines[0].startswith("CHECK model-load FAIL")
    assert expected in lines[0]
    assert "cold load" not in lines[0]


def test_measure_load_fails_when_the_connection_drops(server: tuple[str, type[_Handler]]) -> None:
    url, handler = server
    handler.gen_drop = True
    lines = _probe(url, MEASURE_LOAD="1")
    assert lines[0].startswith("CHECK model-load FAIL")
    assert "cold load" not in lines[0]


def test_measure_load_fails_on_timeout(server: tuple[str, type[_Handler]]) -> None:
    url, handler = server
    handler.gen_delay = 4.0
    lines = _probe(url, MEASURE_LOAD="1", LOAD_TIMEOUT_S="1")
    assert lines[0].startswith("CHECK model-load FAIL")
    assert "cold load" not in lines[0]


def test_measure_load_fails_when_ps_does_not_list_the_model(
    server: tuple[str, type[_Handler]],
) -> None:
    url, handler = server
    handler.loads_model = False
    lines = _probe(url, MEASURE_LOAD="1")
    assert lines[0].startswith("CHECK model-load FAIL")
    assert "not listed" in lines[0]
    assert "cold load" not in lines[0]


def test_measure_load_truncates_a_long_error_text(server: tuple[str, type[_Handler]]) -> None:
    url, handler = server
    handler.gen_status = 500
    handler.gen_body = json.dumps({"error": "x" * 5000}).encode()
    handler.loads_model = False
    lines = _probe(url, MEASURE_LOAD="1")
    assert lines[0].startswith("CHECK model-load FAIL")
    assert len(lines[0]) < 500

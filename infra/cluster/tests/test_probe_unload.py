"""Tests for probe.sh `model-load`: always unload, verify the unload, never leak (T0.6 fix).

A local HTTP server observes the requests (a plumbing seam, not a model fake). Names are synthetic.
"""

import http.server
import json
import os
import shutil
import stat
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "feasibility" / "probe.sh"
GEN = "qwen3.8:27b-q8_0"
_RELEASE = threading.Event()  # set when a test ends: frees handlers that wait for it


class _S(http.server.BaseHTTPRequestHandler):
    seen: ClassVar[list[str]] = []
    gen_status: ClassVar[int] = 200
    gen_body: ClassVar[bytes] = b"{}"
    gen_delay: ClassVar[float] = 0.0
    unload_status: ClassVar[int] = 200
    ps_status_when_loaded: ClassVar[int] = 200
    loaded: ClassVar[bool] = False

    def _reply(self, body: bytes, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # http.server API
        cls = type(self)
        cls.seen.append("GET ps")
        if cls.loaded:
            self._reply(b'{"models":[{"name":"%s"}]}' % GEN.encode(), cls.ps_status_when_loaded)
        else:
            self._reply(b'{"models":[]}')

    def do_POST(self) -> None:  # http.server API
        cls = type(self)
        keep = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["keep_alive"]
        cls.seen.append(f"POST keep_alive={keep}")
        if keep == 0:
            if cls.unload_status < 300:
                cls.loaded = False
            self._reply(b"{}", cls.unload_status)
            return
        _RELEASE.wait(cls.gen_delay)  # blocks until the fixture ends: no race with the timeout
        cls.loaded = cls.gen_status < 300 and b"error" not in cls.gen_body
        self._reply(cls.gen_body, cls.gen_status)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


@pytest.fixture
def srv() -> Iterator[tuple[str, type[_S]]]:
    _RELEASE.clear()
    _S.seen = []
    _S.gen_status, _S.gen_body, _S.gen_delay = 200, b"{}", 0.0
    _S.unload_status, _S.ps_status_when_loaded, _S.loaded = 200, 200, False
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _S)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}", _S
    _RELEASE.set()
    httpd.shutdown()


def _probe(url: str, tmp: Path, **extra: str) -> str:
    proc_root = tmp / "proc"
    proc_root.mkdir(exist_ok=True)
    bindir = tmp / "bin"
    bindir.mkdir(exist_ok=True)
    fake_id = bindir / "id"
    real_id = shutil.which("id") or "id"
    fake_id.write_text(f'#!/bin/sh\n[ "$1" = -un ] && echo LoginX && exit 0\nexec {real_id} "$@"\n')
    fake_id.chmod(fake_id.stat().st_mode | stat.S_IXUSR)
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}", "OLLAMA_URL": url,
           "PROBE_PROC_ROOT": str(proc_root), "PROBE_CHECKS": "model-load", "MEASURE_LOAD": "1",
           "GEN_MODEL": GEN, **extra}  # fmt: skip
    proc = subprocess.run(  # noqa: S603  # fixed argv, no shell
        [shutil.which("bash") or "bash", str(SCRIPT)],
        capture_output=True, text=True, check=False, env=env, timeout=90,
    )  # fmt: skip
    assert proc.returncode == 0, proc.stderr
    return next(x for x in proc.stdout.splitlines() if x.startswith("CHECK model-load"))


def test_timeout_still_sends_the_unload(srv: tuple[str, type[_S]], tmp_path: Path) -> None:
    url, h = srv
    h.gen_delay = 60.0  # the server never answers within the 1 s curl timeout (load-proof)
    out = _probe(url, tmp_path, LOAD_TIMEOUT_S="1")
    assert out.startswith("CHECK model-load FAIL")
    assert "POST keep_alive=0" in h.seen
    assert not out.rstrip().endswith("000")


def test_unreadable_ps_after_the_load_still_sends_the_unload(
    srv: tuple[str, type[_S]], tmp_path: Path
) -> None:
    url, h = srv
    h.ps_status_when_loaded = 500
    out = _probe(url, tmp_path)
    assert out.startswith("CHECK model-load FAIL")
    assert "/api/ps" in out
    assert "POST keep_alive=0" in h.seen
    assert not h.loaded


def test_unload_answered_500_is_not_reported_as_pass(
    srv: tuple[str, type[_S]], tmp_path: Path
) -> None:
    url, h = srv
    h.unload_status = 500
    out = _probe(url, tmp_path)
    assert out.startswith("CHECK model-load WARN")
    assert "unload by hand" in out
    assert "PASS" not in out


def test_clean_run_unloads_and_confirms_through_ps(
    srv: tuple[str, type[_S]], tmp_path: Path
) -> None:
    url, h = srv
    out = _probe(url, tmp_path)
    assert out.startswith("CHECK model-load PASS cold load")
    assert h.seen == ["GET ps", "POST keep_alive=5m", "GET ps", "POST keep_alive=0", "GET ps"]
    assert not h.loaded


@pytest.mark.parametrize("body", [b"", b"<html>Bad Gateway</html>"])
def test_502_with_an_empty_or_html_body_fails(
    srv: tuple[str, type[_S]], tmp_path: Path, body: bytes
) -> None:
    url, h = srv
    h.gen_status, h.gen_body = 502, body
    out = _probe(url, tmp_path)
    assert out.startswith("CHECK model-load FAIL")
    assert "HTTP 502" in out
    assert "cold load" not in out


def test_unsafe_model_name_is_refused_before_any_request(
    srv: tuple[str, type[_S]], tmp_path: Path
) -> None:
    url, h = srv
    out = _probe(url, tmp_path, GEN_MODEL='x","keep_alive":-1,"y":"')
    assert out.startswith("CHECK model-load FAIL")
    assert h.seen == []


def test_error_body_naming_an_install_path_does_not_leak(
    srv: tuple[str, type[_S]], tmp_path: Path
) -> None:
    url, h = srv
    prefix = tmp_path / "opt" / "LoginX" / "ollama"
    binary = prefix / "bin" / "ollama"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    pdir = tmp_path / "proc" / "4242"
    pdir.mkdir(parents=True)
    (pdir / "cmdline").write_bytes(b"ollama\0serve\0")
    (pdir / "exe").symlink_to(binary)
    h.gen_body = json.dumps({"error": f"cannot open {prefix}/lib/ollama/libggml.so"}).encode()
    out = _probe(url, tmp_path)
    assert out.startswith("CHECK model-load FAIL")
    assert "LoginX" not in out
    assert "<ollama-prefix>/lib/ollama/libggml.so" in out

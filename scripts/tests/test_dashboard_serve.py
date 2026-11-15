"""serve_under_base.sh and the header-free static server of the dashboard e2e tests (T8.3)."""

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "dashboard" / "serve_under_base.sh"
SERVER = ROOT / "apps" / "dashboard" / "e2e" / "static-server.mjs"


def _site(tmp_path: Path) -> Path:
    site = tmp_path / "site"
    (site / "de").mkdir(parents=True)
    (site / "404.html").write_text("<p>nf</p>", encoding="utf-8")
    (site / "de" / "index.html").write_text("<p>de</p>", encoding="utf-8")
    return site


def test_prepare_lays_out_the_base_and_writes_valid_serve_json(tmp_path: Path) -> None:
    site, out = _site(tmp_path), tmp_path / "out"
    env = {**os.environ, "SERVE_PREPARE_ONLY": "1"}
    subprocess.run(  # noqa: S603  # fixed argv
        ["bash", str(SCRIPT), str(site), "/pruefstand", str(out)],  # noqa: S607
        check=True,
        env=env,
        capture_output=True,
        timeout=30,
    )
    assert json.loads((out / "serve.json").read_text(encoding="utf-8")) == {
        "cleanUrls": False,
        "trailingSlash": True,
    }
    assert (out / "pruefstand" / "de" / "index.html").is_file()
    assert (out / "404.html").is_file()


def test_a_bad_base_error_names_the_base(tmp_path: Path) -> None:
    res = subprocess.run(  # noqa: S603  # fixed argv
        ["bash", str(SCRIPT), str(_site(tmp_path)), "pruefstand", str(tmp_path / "o")],  # noqa: S607
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert res.returncode == 2
    assert "got 'pruefstand'" in res.stderr


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_the_static_server_answers_400_for_a_malformed_escape_and_404_for_unknown(
    tmp_path: Path,
) -> None:
    port = _free_port()
    proc = subprocess.Popen(  # noqa: S603  # fixed argv
        ["node", str(SERVER), str(_site(tmp_path)), str(port)],  # noqa: S607
        stdout=subprocess.DEVNULL,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                urllib.request.urlopen(base + "/de/", timeout=2).read()  # noqa: S310
                break
            except OSError:
                time.sleep(0.1)
        for path, status in (("/%E0%A4%A", 400), ("/nope/", 404)):
            with pytest.raises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(base + path, timeout=5)  # noqa: S310
            assert err.value.code == status
        assert urllib.request.urlopen(base + "/de/", timeout=5).status == 200  # noqa: S310
    finally:
        proc.terminate()
        proc.wait(timeout=10)

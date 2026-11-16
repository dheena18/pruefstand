"""vm_llm.sh against the real llama-server and the real Ministral 3 8B GGUF on the VM (D1200).

Starts the server through the real host lock and check slots, asks one German question over the
OpenAI-compatible API, checks that it listens on 127.0.0.1 only, and stops it. Skips where the
binary or the model file is missing (hosted runners). Run on the VM, never during a gate run:
``uv run pytest -m live scripts/models/tests/test_vm_llm_live.py``.
"""

import os
import socket
import subprocess
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "models" / "vm_llm.sh"
MODEL = (
    Path(os.environ.get("VM_LLM_MODELS_DIR", Path.home() / ".cache/pruefstand/models"))
    / "Ministral-3-8B-Instruct-2512-Q4_K_M.gguf"
)
BIN = Path(os.environ.get("VM_LLM_BIN_DIR", Path.home() / ".local/llama-cpp/app")) / "llama-server"

pytestmark = [
    pytest.mark.live,
    pytest.mark.slow,
    pytest.mark.skipif(not (MODEL.is_file() and BIN.is_file()), reason="no VM model or binary"),
]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _listeners(port: int) -> list[str]:
    out = subprocess.run(  # noqa: S603
        ["ss", "-ltnH", f"sport = :{port}"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    ).stdout
    return [line.split()[3] for line in out.splitlines() if line.strip()]


def test_start_answer_in_german_on_localhost_only_and_stop(tmp_path: Path) -> None:
    port = _free_port()
    env = {k: v for k, v in os.environ.items() if k != "PRUEFSTAND_LOCK_HELD"}
    env |= {"VM_LLM_PORT": str(port), "VM_LLM_STATE_DIR": str(tmp_path), "VM_LLM_MAX_MIN": "15"}

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        cmd = ["bash", str(SCRIPT), *args]
        return subprocess.run(  # noqa: S603
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )

    started = run("start", "8b")
    assert started.returncode == 0, started.stderr
    try:
        assert _listeners(port) == [f"127.0.0.1:{port}"]
        body = {
            "messages": [{"role": "user", "content": "Wofür steht die Abkürzung BGB? Ein Satz."}],
            "temperature": 0,
            "max_tokens": 40,
        }
        resp = httpx.post(f"http://127.0.0.1:{port}/v1/chat/completions", json=body, timeout=300)
        resp.raise_for_status()
        answer = resp.json()["choices"][0]["message"]["content"]
        assert "Gesetzbuch" in answer
    finally:
        stopped = run("stop")
    assert stopped.returncode == 0
    assert _listeners(port) == []
    assert run("status").returncode == 3

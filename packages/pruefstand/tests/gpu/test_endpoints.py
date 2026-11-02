"""T3.1a ``gpu`` smoke tests: the one Ollama server through the VM tunnel (ADR-0018, ADR-0019).

Run on the VM under the GPU lock: ``pruefstand-lock make test-gpu`` (``make test-gpu-locked``). They need the
day-mode set loaded (``make gpu-up``) and, for the reranker, the dev stack (``rerank-cpu`` on the dev port).
"""

import math
import os
import secrets
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

pytestmark = pytest.mark.gpu

REPO = Path(__file__).resolve().parents[4]
CATALOGUE = yaml.safe_load((REPO / "infra" / "gpu" / "models.yaml").read_text(encoding="utf-8"))
ENTRIES = {m["tag"]: m for m in CATALOGUE["models"]}
GEN, EMBED, JUDGE = "qwen3.8:27b-q8_0", "bge-m3", "gemma3:12b"
GEN_DIGEST = "8f5fb6b71ea00052cbe8545738c55ce61112c4e571cb60ca4dad00b131766039"
GPU0 = os.environ.get("OLLAMA_GPU0_URL", "http://127.0.0.1:11434")
GPU1 = os.environ.get("OLLAMA_GPU1_URL", "http://127.0.0.1:11434")
RERANK = os.environ.get("RERANK_URL", "http://127.0.0.1:18201")
PARAGRAPH = (
    "Die Kündigungsfrist für Arbeitnehmer beträgt nach § 622 Absatz 1 BGB vier Wochen zum Fünfzehnten "
    "oder zum Ende eines Kalendermonats. Verlängert sich die Frist für eine Kündigung durch den "
    "Arbeitgeber, wenn das Arbeitsverhältnis in dem Betrieb oder Unternehmen zwei Jahre bestanden hat, "
    "so beträgt sie einen Monat zum Ende eines Kalendermonats. "
)


def _client(base: str) -> httpx.Client:
    return httpx.Client(base_url=base, timeout=httpx.Timeout(600.0))


def _chat(prompt: str, tag: str = GEN, num_predict: int | None = None) -> dict[str, Any]:
    options = {**ENTRIES[tag]["options"], **({"num_predict": num_predict} if num_predict else {})}
    body = {
        "model": tag, "stream": False, "think": False, "options": options,
        "messages": [{"role": "user", "content": prompt}],
    }  # fmt: skip
    with _client(GPU0) as client:
        resp = client.post("/api/chat", json=body)
    resp.raise_for_status()
    return resp.json()  # type: ignore[no-any-return]


def test_both_lane_urls_reach_the_same_server() -> None:
    names = []
    for url in (GPU0, GPU1):
        with _client(url) as client:
            resp = client.get("/api/tags")
        assert resp.status_code == 200
        names.append(sorted(m["name"] for m in resp.json()["models"]))
    assert names[0] == names[1]
    assert GEN in names[0]


def test_the_generator_answers_in_german_without_a_think_block() -> None:
    answer = _chat("Was regelt § 622 BGB? Antworte kurz auf Deutsch.")["message"]["content"]
    assert "Kündigungsfrist" in answer
    assert "<think>" not in answer


def test_a_long_prompt_reaches_the_model_and_a_preloaded_model_does_not_reload() -> None:
    def prompt(repeats: int) -> str:
        return (
            f"Vorgang {secrets.token_hex(8)}.\n"
            + PARAGRAPH * repeats
            + "\nFasse den Text in einem Satz zusammen."
        )

    probe = _chat(prompt(40), num_predict=1)
    per_repeat = probe["prompt_eval_count"] / 40
    repeats = math.ceil(7000 / per_repeat)
    res = _chat(prompt(repeats), num_predict=1)
    assert res["prompt_eval_count"] >= 6900
    assert res["load_duration"] < 1_000_000_000  # < 1 s: no reload after the preload (AI11-01)


def test_bge_m3_returns_1024_dimensional_vectors() -> None:
    with _client(GPU0) as client:
        resp = client.post(
            "/api/embed",
            json={
                "model": EMBED,
                "input": ["Kündigungsfrist"],
                "options": ENTRIES[EMBED]["options"],
            },
        )
    resp.raise_for_status()
    assert len(resp.json()["embeddings"][0]) == 1024


def test_rerank_cpu_orders_the_relevant_passage_first() -> None:
    texts = [
        "Der Hund läuft über die Wiese und bellt die Nachbarn an.",
        "Nach § 622 BGB beträgt die Kündigungsfrist für Arbeitnehmer vier Wochen.",
    ]
    with httpx.Client(timeout=120.0) as client:
        resp = client.post(
            RERANK + "/rerank",
            json={"query": "Wie lang ist die Kündigungsfrist?", "texts": texts, "truncate": True},
        )
    resp.raise_for_status()
    assert resp.json()[0]["index"] == 1


def test_ps_shows_only_the_day_models_with_the_pins_fully_in_vram() -> None:
    with _client(GPU0) as client:
        models = client.get("/api/ps").json()["models"]
    assert {m["name"] for m in models} == {GEN, EMBED, JUDGE}
    for m in models:
        assert m["digest"] == ENTRIES[m["name"]]["digest"], m["name"]
        assert m["size_vram"] == m["size"], m["name"]
    assert next(m for m in models if m["name"] == GEN)["digest"] == GEN_DIGEST


def test_status_places_the_generator_and_the_judge_on_different_cards() -> None:
    lib = REPO / "infra" / "gpu" / "lib" / "cluster_ssh.sh"
    proc = subprocess.run(  # noqa: S603
        ["bash", "-c", f'. "{lib}"; cluster_op status'],  # noqa: S607
        capture_output=True, text=True, check=True, timeout=120,
    )  # fmt: skip
    rows = {
        ln.split(",", 2)[0]: ln.split(",", 2)[2]
        for ln in proc.stdout.splitlines()[1:]
        if ln.count(",") >= 2
    }
    assert rows[f"placement:{GEN}"] != rows[f"placement:{JUDGE}"]
    assert "+" not in rows[f"placement:{GEN}"]

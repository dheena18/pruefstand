"""T3.1a CPU tests: ``switch-mode.sh`` and ``unload-all.sh`` (API loads/unloads only, ADR-0018)."""

import json
import re
from typing import Any

import pytest
from gpu_world import CATALOGUE, DAY_TAGS, ENTRIES, GpuWorld, ps_model

EXTRA = "jeffh/intfloat-multilingual-e5-large-instruct:f16"


def _loads(out: str) -> list[dict[str, Any]]:
    rows = [
        json.loads(m.group(2)) for m in re.finditer(r"^DRY-RUN POST (\S+) (\{.*\})$", out, re.M)
    ]
    return [r for r in rows if r.get("keep_alive") != 0]


def _preload(tag: str) -> dict[str, Any]:
    return {
        "model": tag,
        "keep_alive": ENTRIES[tag]["keep_alive"],
        "options": ENTRIES[tag]["options"],
    }


@pytest.mark.parametrize("mode", ["day", "night"])
def test_dry_run_with_an_answering_server_neither_starts_nor_stops_one(
    gpu: GpuWorld, mode: str
) -> None:
    gpu.set_ps([])
    res = gpu.script("switch-mode.sh", mode, "--dry-run")
    assert res.rc == 0, res.err
    assert "start-ollama" not in res.out + "".join(gpu.stubs.calls("ssh"))
    assert "stop-ollama" not in res.out + "".join(gpu.stubs.calls("ssh"))
    assert not gpu.stubs.calls("ssh")
    assert "/v1/" not in res.out


def test_day_and_night_load_the_same_set_generator_before_the_judge(gpu: GpuWorld) -> None:
    gpu.set_ps([])
    day = _loads(gpu.script("switch-mode.sh", "day", "--dry-run").out)
    night = _loads(gpu.script("switch-mode.sh", "night", "--dry-run").out)
    assert day == night
    tags = [b["model"] for b in day]
    assert tags == list(DAY_TAGS)
    assert tags.index("qwen3.8:27b-q8_0") < tags.index("gemma3:12b")


def test_every_preload_body_is_model_keep_alive_and_the_catalogue_options(gpu: GpuWorld) -> None:
    gpu.set_ps([])
    out = gpu.script("switch-mode.sh", "day", "--dry-run").out
    assert re.findall(r"^DRY-RUN POST \S+/api/generate ", out, re.M)
    for body in _loads(out):
        assert body == _preload(body["model"])
        assert set(body) == {"model", "keep_alive", "options"}


def test_a_leftover_catalogue_model_is_unloaded_before_the_judge_loads(gpu: GpuWorld) -> None:
    gpu.set_ps([ps_model(EXTRA)])
    out = gpu.script("switch-mode.sh", "day", "--dry-run").out
    lines = [ln for ln in out.splitlines() if ln.startswith("DRY-RUN POST")]
    unload = next(
        i for i, ln in enumerate(lines) if f'"model":"{EXTRA}"' in ln and '"keep_alive":0' in ln
    )
    judge = next(i for i, ln in enumerate(lines) if '"model":"gemma3:12b"' in ln)
    assert unload < judge


def test_models_already_resident_are_not_loaded_again(gpu: GpuWorld) -> None:
    out = gpu.script("switch-mode.sh", "day", "--dry-run").out
    assert _loads(out) == []
    assert "already resident" in out


def test_a_resident_model_with_another_context_is_reloaded(gpu: GpuWorld) -> None:
    wrong = ps_model("gemma3:12b")
    wrong["context_length"] = 4096
    gpu.set_ps([ps_model("qwen3.8:27b-q8_0"), ps_model("bge-m3"), wrong])
    out = gpu.script("switch-mode.sh", "day", "--dry-run").out
    assert [b["model"] for b in _loads(out)] == ["gemma3:12b"]


def test_a_non_catalogue_model_of_another_user_is_left_alone(gpu: GpuWorld) -> None:
    other = {**ps_model("bge-m3"), "name": "llama3:8b", "model": "llama3:8b"}
    gpu.set_ps([other])
    res = gpu.script("switch-mode.sh", "day", "--dry-run")
    assert "llama3:8b" not in "".join(
        ln for ln in res.out.splitlines() if ln.startswith("DRY-RUN POST")
    )
    assert "WARN" in res.out
    assert "llama3:8b" in res.out


def test_the_real_run_posts_the_same_bodies_and_never_calls_the_cluster(gpu: GpuWorld) -> None:
    gpu.set_ps([])
    res = gpu.script("switch-mode.sh", "day")
    assert res.rc == 0, res.err
    assert gpu.posts() == [_preload(t) for t in DAY_TAGS]
    assert not gpu.stubs.calls("ssh")


def test_a_failing_load_fails_the_switch(gpu: GpuWorld) -> None:
    gpu.set_ps([])
    gpu.curl(generate_rc=22)
    assert gpu.script("switch-mode.sh", "day").rc == 1


def test_a_down_server_is_started_once_and_awaited(gpu: GpuWorld) -> None:
    gpu.set_ps([])
    gpu.curl(tags_fail_first=1)
    res = gpu.script("switch-mode.sh", "day")
    assert res.rc == 0, res.err
    starts = [c for c in gpu.stubs.calls("ssh") if "start-ollama.sh" in c]
    assert len(starts) == 1
    assert "/data/dheena/pruefstand-bin/start-ollama.sh" in starts[0]
    assert len(gpu.posts()) == 3


def test_a_server_that_never_answers_fails_after_the_wait(gpu: GpuWorld) -> None:
    gpu.curl(tags_fail_first=10_000)
    res = gpu.script("switch-mode.sh", "day", SERVER_WAIT_S="1")
    assert res.rc == 1
    assert len([c for c in gpu.stubs.calls("ssh") if "start-ollama.sh" in c]) == 1


def test_the_judge_lane_url_is_used_for_the_judge(gpu: GpuWorld) -> None:
    gpu.set_ps([])
    res = gpu.script("switch-mode.sh", "day", "--dry-run", OLLAMA_GPU1_URL="http://127.0.0.1:11435")
    judge = next(ln for ln in res.out.splitlines() if '"model":"gemma3:12b"' in ln)
    assert "http://127.0.0.1:11435/api/generate" in judge
    gen = next(ln for ln in res.out.splitlines() if '"model":"qwen3.8:27b-q8_0"' in ln)
    assert "http://127.0.0.1:11434/api/generate" in gen


def test_unload_all_unloads_every_resident_catalogue_model_and_keeps_the_server(
    gpu: GpuWorld,
) -> None:
    res = gpu.script("unload-all.sh", "--dry-run")
    assert res.rc == 0, res.err
    unloads = [
        json.loads(m.group(1)) for m in re.finditer(r"^DRY-RUN POST \S+ (\{.*\})$", res.out, re.M)
    ]
    assert sorted(b["model"] for b in unloads) == sorted(DAY_TAGS)
    assert all(b == {"model": b["model"], "keep_alive": 0} for b in unloads)
    assert "stop-ollama" not in res.out
    assert not gpu.stubs.calls("ssh")


def test_the_catalogue_digests_in_the_yaml_are_the_pins() -> None:
    assert {m["tag"] for m in CATALOGUE["models"]} >= set(DAY_TAGS)


def test_a_resident_bge_m3_listed_as_latest_is_not_loaded_or_unloaded(gpu: GpuWorld) -> None:
    out = gpu.script("switch-mode.sh", "day", "--dry-run").out
    assert "bge-m3 already resident" in out
    assert "unloading" not in out
    assert _loads(out) == []


def test_unload_all_unloads_bge_m3_by_its_catalogue_tag(gpu: GpuWorld) -> None:
    res = gpu.script("unload-all.sh", "--dry-run")
    assert '"model":"bge-m3","keep_alive":0' in res.out
    assert "bge-m3:latest" not in res.out

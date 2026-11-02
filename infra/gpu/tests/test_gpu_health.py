"""T3.1a CPU tests: ``health.sh`` exit codes 0/10-16, the CSV and ``--repair`` (interfaces 1.5)."""

import os
import re

import pytest
from gpu_world import DAY_TAGS, DF_HEAD, ENTRIES, GpuWorld, ps_model, status_csv
from vm_testkit import Result

EXTRA = "jeffh/intfloat-multilingual-e5-large-instruct:f16"


def _csv(res: Result) -> dict[str, tuple[str, str]]:
    rows = [ln.split(",", 2) for ln in res.out.splitlines() if ln.strip()]
    assert rows[0] == ["check", "status", "detail"], res.out
    return {r[0]: (r[1], r[2]) for r in rows[1:]}


def _healthy(gpu: GpuWorld, **kw: object) -> None:
    gpu.ssh(status_csv(sums=gpu.expected_sums(), **kw))  # type: ignore[arg-type]


def test_a_healthy_world_exits_0_and_names_the_card_of_every_model(gpu: GpuWorld) -> None:
    _healthy(gpu)
    res = gpu.script("health.sh")
    assert res.rc == 0, res.out + res.err
    rows = _csv(res)
    assert {s for s, _ in rows.values()} <= {"OK", "INFO"}
    assert rows["placement:gemma3:12b"][1] == "gpu=1"
    assert rows["placement:qwen3.8:27b-q8_0"][1] == "gpu=0"
    assert rows["data-root"][0] == "OK"


def test_low_free_space_on_the_cluster_disk_warns_but_exits_0(gpu: GpuWorld) -> None:
    _healthy(gpu, free_kb=1_048_576)
    res = gpu.script("health.sh")
    assert res.rc == 0
    assert _csv(res)["disk-models"][0] == "WARN"


def test_a_refused_endpoint_exits_11(gpu: GpuWorld) -> None:
    gpu.curl(tags_fail_first=10_000)
    assert gpu.script("health.sh").rc == 11
    assert not gpu.stubs.calls("ssh") or not any(
        "start-ollama" in c for c in gpu.stubs.calls("ssh")
    )


def test_a_mode_model_that_is_not_resident_exits_11(gpu: GpuWorld) -> None:
    gpu.set_ps([ps_model(t) for t in DAY_TAGS[:2]])
    res = gpu.script("health.sh")
    assert res.rc == 11
    assert _csv(res)["resident:gemma3:12b"][0] == "FAIL"


def test_low_free_vram_on_a_card_exits_10(gpu: GpuWorld) -> None:
    _healthy(gpu, gpu_used=(36000, 45900))
    res = gpu.script("health.sh")
    assert res.rc == 10
    assert _csv(res)["vram:1"][0] == "FAIL"


def test_a_resident_digest_other_than_the_catalogue_exits_13(gpu: GpuWorld) -> None:
    gpu.set_ps(
        [ps_model("qwen3.8:27b-q8_0"), ps_model("bge-m3"), ps_model("gemma3:12b", digest="0" * 64)]
    )
    assert gpu.script("health.sh").rc == 13


def test_size_vram_below_size_exits_15(gpu: GpuWorld) -> None:
    gpu.set_ps(
        [ps_model("qwen3.8:27b-q8_0", vram_ratio=0.8), ps_model("bge-m3"), ps_model("gemma3:12b")]
    )
    res = gpu.script("health.sh")
    assert res.rc == 15
    assert _csv(res)["placement:qwen3.8:27b-q8_0"][0] == "FAIL"


def test_a_model_spread_over_both_cards_exits_15(gpu: GpuWorld) -> None:
    _healthy(gpu, spread="0+1")
    assert gpu.script("health.sh").rc == 15


def test_status_unreachable_over_ssh_exits_12(gpu: GpuWorld) -> None:
    gpu.ssh("", status_rc=255)
    assert gpu.script("health.sh").rc == 12


def test_out_of_date_cluster_scripts_exit_14(gpu: GpuWorld) -> None:
    gpu.ssh(status_csv(sums="1" * 64))
    assert gpu.script("health.sh").rc == 14
    gpu.ssh(
        status_csv(
            sums=gpu.expected_sums(), extra=["bin-integrity,FAIL,sha256sum -c failed"]
        ).replace("bin-integrity,OK,sha256sum -c passed\n", "")
    )
    assert gpu.script("health.sh").rc == 14


def test_data_root_missing_exits_16(gpu: GpuWorld) -> None:
    res = gpu.script("health.sh", PRUEFSTAND_DATA_ROOT=str(gpu.root / "nope"))
    assert res.rc == 16
    assert _csv(res)["data-root"][0] == "FAIL"


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_data_root_not_writable_exits_16(gpu: GpuWorld) -> None:
    gpu.data_root.chmod(0o500)
    try:
        assert gpu.script("health.sh").rc == 16
    finally:
        gpu.data_root.chmod(0o700)


def test_data_root_with_less_than_20_gb_free_exits_16(gpu: GpuWorld) -> None:
    gpu.stubs.add("df", [("*", DF_HEAD + "/dev/vda 500000000 480000000 19000000 96% /mnt", 0)])
    res = gpu.script("health.sh")
    assert res.rc == 16
    assert gpu.script("health.sh", PRUEFSTAND_DATA_ROOT_MIN_FREE_GB="10").rc == 0


def test_the_data_root_failure_wins_over_the_others(gpu: GpuWorld) -> None:
    gpu.curl(tags_fail_first=10_000)
    assert gpu.script("health.sh", PRUEFSTAND_DATA_ROOT=str(gpu.root / "nope")).rc == 16


def _loads_and_unloads(gpu: GpuWorld) -> tuple[list[str], list[str]]:
    posts = gpu.posts()
    return [p["model"] for p in posts if p["keep_alive"] != 0], [
        p["model"] for p in posts if p["keep_alive"] == 0
    ]


def test_repair_with_a_refused_endpoint_starts_the_server_once_then_loads_the_day_set(
    gpu: GpuWorld,
) -> None:
    gpu.set_ps([])
    gpu.curl(tags_fail_first=2)
    res = gpu.script("health.sh", "--repair")
    starts = [c for c in gpu.stubs.calls("ssh") if "start-ollama.sh" in c]
    assert len(starts) == 1, res.out + res.err
    assert _loads_and_unloads(gpu)[0] == list(DAY_TAGS)


def test_repair_with_an_answering_server_never_starts_one(gpu: GpuWorld) -> None:
    gpu.script("health.sh", "--repair")
    assert not [c for c in gpu.stubs.calls("ssh") if "start-ollama" in c]


def test_repair_unloads_a_leftover_catalogue_model_before_the_judge_loads(gpu: GpuWorld) -> None:
    gpu.set_ps([ps_model("qwen3.8:27b-q8_0"), ps_model("bge-m3"), ps_model(EXTRA)])
    gpu.script("health.sh", "--repair")
    models = [(p["model"], p["keep_alive"]) for p in gpu.posts()]
    assert (EXTRA, 0) in models
    assert models.index((EXTRA, 0)) < next(i for i, m in enumerate(models) if m[0] == "gemma3:12b")


def test_repair_leaves_a_non_catalogue_model_alone_and_warns(gpu: GpuWorld) -> None:
    other = {**ps_model("bge-m3"), "name": "llama3:8b", "model": "llama3:8b"}
    gpu.set_ps([ps_model("qwen3.8:27b-q8_0"), ps_model("bge-m3"), ps_model("gemma3:12b"), other])
    res = gpu.script("health.sh", "--repair")
    assert all(p["model"] != "llama3:8b" for p in gpu.posts())
    assert _csv(res)["extra:llama3:8b"][0] == "WARN"


def test_repair_in_night_mode_loads_the_same_set_as_day(gpu: GpuWorld) -> None:
    gpu.set_ps([])
    gpu.script("health.sh", "--repair", "--mode", "day")
    day = _loads_and_unloads(gpu)[0]
    gpu.stubs.log.write_text("")
    gpu.script("health.sh", "--repair", "--mode", "night")
    assert _loads_and_unloads(gpu)[0] == day == list(DAY_TAGS)


def test_every_repair_preload_is_model_keep_alive_options(gpu: GpuWorld) -> None:
    gpu.set_ps([])
    gpu.script("health.sh", "--repair")
    for body in gpu.posts():
        assert body == {
            "model": body["model"],
            "keep_alive": ENTRIES[body["model"]]["keep_alive"],
            "options": ENTRIES[body["model"]]["options"],
        }


@pytest.mark.parametrize("args", [("--mode", "datagen"), ("--mode",), ("--bogus",)])
def test_bad_arguments_exit_64(gpu: GpuWorld, args: tuple[str, ...]) -> None:
    assert gpu.script("health.sh", *args).rc == 64


def test_the_csv_never_contains_a_real_path_or_the_tunnel_host(gpu: GpuWorld) -> None:
    _healthy(gpu)
    res = gpu.script("health.sh")
    assert not re.search(r"/home/|/data/dheena/Models", res.out)


def test_models_reported_with_latest_pass_the_digest_and_placement_checks(gpu: GpuWorld) -> None:
    """bge-m3 is listed as bge-m3:latest by /api/ps and in status.sh (first real run)."""
    _healthy(gpu)
    assert '"name": "bge-m3:latest"' in gpu.ps_file.read_text()
    res = gpu.script("health.sh")
    assert res.rc == 0, res.out
    rows = _csv(res)
    assert rows["resident:bge-m3"][0] == "OK"
    assert rows["placement:bge-m3"] == ("OK", "gpu=0")


def test_another_tag_of_the_same_model_is_not_the_catalogue_model(gpu: GpuWorld) -> None:
    other = {**ps_model("bge-m3"), "name": "bge-m3:other", "model": "bge-m3:other"}
    gpu.set_ps([ps_model("qwen3.8:27b-q8_0"), other, ps_model("gemma3:12b")])
    res = gpu.script("health.sh")
    assert res.rc == 11
    assert _csv(res)["resident:bge-m3"][0] == "FAIL"
    assert _csv(res)["extra:bge-m3:other"][0] == "WARN"


def test_a_missing_start_script_is_a_warning_row_and_does_not_fail(gpu: GpuWorld) -> None:
    gpu.ssh(status_csv(sums=gpu.expected_sums(), extra=["start-script,WARN,missing"]))
    res = gpu.script("health.sh")
    assert res.rc == 0
    assert _csv(res)["start-script"][0] == "WARN"

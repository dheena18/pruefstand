"""T3.1a CPU tests: ``status.sh`` (CSV ``check,status,detail``; placement join, disk, env)."""

import json
from pathlib import Path

from gpu_testkit import GEN_DIGEST, ClusterWorld, add_proc
from vm_testkit import Result

TAG = "qwen3.8:27b-q8_0"
LAYER = "2bb22714289826d7b9e0ba376c3ce47d08bce39abe598745857c44d88c09bdbf"
DF_HEAD = "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
DF_OK = DF_HEAD + "/dev/sdb1 500000000 480000000 14000000 97% /data"
DF_LOW = DF_OK.replace("14000000", "1048576")


def _csv(res: Result) -> dict[str, tuple[str, str]]:
    rows = [ln.split(",", 2) for ln in res.out.splitlines() if ln.strip()]
    assert rows[0] == ["check", "status", "detail"], res.out
    return {r[0]: (r[1], r[2]) for r in rows[1:]}


def _ps(world: ClusterWorld, *, vram: int = 35_000_000_000) -> str:
    del world
    model = {
        "name": TAG, "model": TAG, "size": 35_000_000_000, "digest": GEN_DIGEST,
        "details": {"family": "qwen35"}, "expires_at": "2026-11-03T10:00:00Z",
        "size_vram": vram, "context_length": 8192,
    }  # fmt: skip
    return json.dumps({"models": [model]})


def _manifest(world: ClusterWorld) -> None:
    path = world.models / "manifests" / "registry.ollama.ai" / "library" / "qwen3.8" / "27b-q8_0"
    path.parent.mkdir(parents=True)
    layers = [
        {"mediaType": "application/vnd.ollama.image.projector", "digest": "sha256:" + "ab" * 32},
        {"mediaType": "application/vnd.ollama.image.model", "digest": f"sha256:{LAYER}"},
    ]
    path.write_text(json.dumps({"schemaVersion": 2, "layers": layers}))


def _healthy(world: ClusterWorld, *, df: str = DF_OK) -> None:
    world.add_serve(4242)
    world.stub_server([4242])
    tags = {"models": [{"name": TAG, "digest": GEN_DIGEST, "size": 29978242050}]}
    world.stubs.add("curl", [("*api/tags*", json.dumps(tags), 0), ("*api/ps*", _ps(world), 0)])
    world.stubs.add("df", [("*", df, 0)])
    world.stubs.add(
        "nvidia-smi",
        [
            ("*query-gpu*", "0, GPU-aaa, 36000, 46068\n1, GPU-bbb, 12, 46068", 0),
            ("*query-compute-apps*", "5001, GPU-aaa, 35000", 0),
        ],
    )
    _manifest(world)
    blob = f"{world.models}/blobs/sha256-{LAYER}"
    add_proc(
        world.proc, 5001, ["/usr/local/bin/ollama", "runner", "--model", blob, "--port", "40000"]
    )


def test_healthy_server_reports_only_ok_and_info(world: ClusterWorld) -> None:
    _healthy(world)
    res = world.script("status.sh")
    assert res.rc == 0, res.err
    rows = _csv(res)
    assert {s for s, _ in rows.values()} <= {"OK", "INFO"}, rows
    assert rows["server"] == ("OK", "pid=4242")
    assert rows["env"][0] == "OK"
    assert rows["disk-models"][0] == "OK"
    assert rows["placement:" + TAG] == ("OK", "gpu=0")
    assert rows["gpu:0"][1].startswith("uuid=GPU-aaa used_mib=36000 total_mib=46068")
    assert "size_vram=35000000000" in rows["ps:" + TAG][1]
    assert rows["bin-integrity"][0] == "OK"
    assert rows["bin-sums"][1].startswith("sha256=")


def test_env_differences_of_the_running_server_are_warned_by_key(world: ClusterWorld) -> None:
    _healthy(world)
    world.add_serve(4242, {"OLLAMA_MAX_LOADED_MODELS": "1", "OLLAMA_MODELS": "/elsewhere"})
    rows = _csv(world.script("status.sh"))
    assert rows["env:OLLAMA_MAX_LOADED_MODELS"][0] == "WARN"
    assert "expected=3" in rows["env:OLLAMA_MAX_LOADED_MODELS"][1]
    assert "actual=1" in rows["env:OLLAMA_MAX_LOADED_MODELS"][1]
    assert rows["env:OLLAMA_MODELS"][0] == "WARN"
    assert "env" not in rows


def test_an_unset_expected_variable_is_a_warning(world: ClusterWorld) -> None:
    _healthy(world)
    add_proc(
        world.proc, 4242, ["/usr/local/bin/ollama", "serve"], {"OLLAMA_HOST": "127.0.0.1:11434"}
    )
    rows = _csv(world.script("status.sh"))
    assert "actual=unset" in rows["env:OLLAMA_KV_CACHE_TYPE"][1]


def test_low_free_space_on_the_models_disk_warns(world: ClusterWorld) -> None:
    _healthy(world, df=DF_LOW)
    row = _csv(world.script("status.sh"))["disk-models"]
    assert row[0] == "WARN"
    assert "free_kb=1048576" in row[1]
    assert "min_free_gb=2" in row[1]


def test_two_ollama_serve_processes_fail(world: ClusterWorld) -> None:
    _healthy(world)
    world.add_serve(4343)
    world.stub_server([4242, 4343])
    res = world.script("status.sh")
    assert res.rc == 1
    assert _csv(res)["second-server"][0] == "FAIL"


def test_no_server_fails_with_a_clear_row(world: ClusterWorld) -> None:
    _healthy(world)
    world.stub_server([])
    res = world.script("status.sh")
    assert res.rc == 1
    assert _csv(res)["server"][0] == "FAIL"


def test_foreign_gpu_process_is_flagged(world: ClusterWorld) -> None:
    _healthy(world)
    world.stubs.add(
        "nvidia-smi",
        [
            ("*query-gpu*", "0, GPU-aaa, 36000, 46068\n1, GPU-bbb, 900, 46068", 0),
            ("*query-compute-apps*", "5001, GPU-aaa, 35000\n9999, GPU-bbb, 900", 0),
        ],
    )
    add_proc(world.proc, 9999, ["python3", "train.py"])
    rows = _csv(world.script("status.sh"))
    assert rows["gpu-proc:9999"][0] == "WARN"
    assert "foreign" in rows["gpu-proc:9999"][1]
    assert rows["gpu-proc:5001"][0] == "INFO"


def test_a_model_on_both_cards_is_reported_as_spread(world: ClusterWorld) -> None:
    _healthy(world)
    world.stubs.add(
        "nvidia-smi",
        [
            ("*query-gpu*", "0, GPU-aaa, 20000, 46068\n1, GPU-bbb, 20000, 46068", 0),
            ("*query-compute-apps*", "5001, GPU-aaa, 20000\n5002, GPU-bbb, 20000", 0),
        ],
    )
    blob = f"{world.models}/blobs/sha256-{LAYER}"
    add_proc(world.proc, 5002, ["/usr/local/bin/ollama", "runner", "--model", blob])
    row = _csv(world.script("status.sh"))["placement:" + TAG]
    assert row[0] == "WARN"
    assert row[1].startswith("gpu=0+1")


def test_unknown_placement_when_no_runner_matches(world: ClusterWorld) -> None:
    _healthy(world)
    (world.proc / "5001" / "cmdline").write_bytes(
        b"ollama\0runner\0--model\0/x/sha256-" + b"cd" * 32 + b"\0"
    )
    row = _csv(world.script("status.sh"))["placement:" + TAG]
    assert row[0] == "WARN"
    assert "unknown" in row[1]


def test_a_modified_script_breaks_bin_integrity(world: ClusterWorld) -> None:
    _healthy(world)
    with (world.bin_dir / "stop-ollama.sh").open("a", encoding="utf-8") as fh:
        fh.write("# tampered\n")
    assert _csv(world.script("status.sh"))["bin-integrity"][0] == "FAIL"


def test_missing_sha256sums_is_a_warning(world: ClusterWorld) -> None:
    _healthy(world)
    (world.bin_dir / "SHA256SUMS").unlink()
    assert _csv(world.script("status.sh"))["bin-integrity"][0] == "WARN"


def test_status_writes_nothing_on_the_cluster(world: ClusterWorld) -> None:
    _healthy(world)
    before = sorted(p for p in Path(world.root).rglob("*") if p.is_file())
    world.script("status.sh")
    assert sorted(p for p in Path(world.root).rglob("*") if p.is_file()) == before


def test_the_start_script_of_record_is_reported_ok_when_it_exists(world: ClusterWorld) -> None:
    _healthy(world)
    row = _csv(world.script("status.sh"))["start-script"]
    assert row[0] == "OK"
    assert str(world.home) not in row[1]


def test_a_missing_start_script_is_a_warning(world: ClusterWorld) -> None:
    _healthy(world)
    (world.home / "start-ollama.sh").unlink()
    res = world.script("status.sh")
    row = _csv(res)["start-script"]
    assert res.rc == 0
    assert row[0] == "WARN"
    assert "~/start-ollama.sh" in row[1]
    assert str(world.home) not in row[1]


def test_a_start_script_that_is_not_executable_is_a_warning(world: ClusterWorld) -> None:
    _healthy(world)
    (world.home / "start-ollama.sh").chmod(0o644)
    assert _csv(world.script("status.sh"))["start-script"][0] == "WARN"


def test_a_dangling_link_as_start_script_is_a_warning(world: ClusterWorld) -> None:
    _healthy(world)
    (world.home / "start-ollama.sh").unlink()
    (world.home / "start-ollama.sh").symlink_to(world.home / "nowhere.sh")
    assert _csv(world.script("status.sh"))["start-script"][0] == "WARN"

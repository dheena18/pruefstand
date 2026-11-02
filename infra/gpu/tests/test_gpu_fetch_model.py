"""T3.1a CPU tests: ``fetch-model.sh`` (pull, digest check, the disk rule, ``--rm``; ADR-0019)."""

import pytest
from gpu_world import ENTRIES, GIB, GpuWorld, status_csv

BGE = "ollama/bge-m3"
JUDGE = "ollama/gemma3:12b"
GEN = "ollama/qwen3.8:27b-q8_0"
RESERVE_KB = 2 * 1024 * 1024


def _need_kb(tag: str) -> int:
    """Model size plus the 2 GiB reserve, in KiB (rounded up)."""
    return int(-(-ENTRIES[tag]["disk_bytes"] // 1024)) + RESERVE_KB


def _remote(gpu: GpuWorld, word: str) -> list[str]:
    return [c for c in gpu.stubs.calls("ssh") if word in c]


def test_enough_free_space_pulls_once_and_accepts_the_pinned_digest(gpu: GpuWorld) -> None:
    gpu.set_tags([])
    gpu.ssh(status_csv(free_kb=_need_kb("bge-m3")), pulled={"bge-m3": ENTRIES["bge-m3"]["digest"]})
    res = gpu.script("fetch-model.sh", BGE)
    assert res.rc == 0, res.out + res.err
    pulls = _remote(gpu, "ollama-op.sh pull bge-m3")
    assert len(pulls) == 1
    assert "/data/dheena/pruefstand-bin/ollama-op.sh" in pulls[0]
    assert not _remote(gpu, "ollama-op.sh rm")


def test_a_model_already_present_with_the_pinned_digest_is_not_pulled(gpu: GpuWorld) -> None:
    gpu.set_tags(["bge-m3"])
    gpu.ssh(status_csv(free_kb=10))  # not even the space matters when there is nothing to pull
    res = gpu.script("fetch-model.sh", BGE)
    assert res.rc == 0, res.err
    assert "already present" in res.out
    assert not _remote(gpu, "ollama-op.sh")


def test_not_enough_free_space_stops_with_17_before_any_pull(gpu: GpuWorld) -> None:
    gpu.set_tags([])
    gpu.ssh(
        status_csv(free_kb=_need_kb("gemma3:12b") - 1),
        pulled={"gemma3:12b": ENTRIES["gemma3:12b"]["digest"]},
    )
    res = gpu.script("fetch-model.sh", JUDGE)
    assert res.rc == 17
    assert "owner" in res.err
    assert "free space first" in res.err
    assert not _remote(gpu, "ollama-op.sh")


def test_the_space_is_read_from_the_cluster_right_before_every_pull(gpu: GpuWorld) -> None:
    gpu.set_tags([])
    gpu.ssh(status_csv(free_kb=_need_kb("bge-m3")), pulled={"bge-m3": ENTRIES["bge-m3"]["digest"]})
    assert gpu.script("fetch-model.sh", BGE).rc == 0
    calls = gpu.stubs.calls("ssh")
    assert "status.sh" in calls[0]
    assert "ollama-op.sh pull" in calls[1]
    gpu.set_tags([])
    gpu.stubs.log.write_text("")
    gpu.ssh(status_csv(free_kb=1000), pulled={"bge-m3": ENTRIES["bge-m3"]["digest"]})
    assert gpu.script("fetch-model.sh", BGE).rc == 17
    assert not _remote(gpu, "ollama-op.sh")


def test_a_digest_mismatch_after_the_pull_removes_the_model_and_exits_1(gpu: GpuWorld) -> None:
    gpu.set_tags([])
    gpu.ssh(status_csv(free_kb=_need_kb("bge-m3")), pulled={"bge-m3": "9" * 64})
    res = gpu.script("fetch-model.sh", BGE)
    assert res.rc == 1
    assert len(_remote(gpu, "ollama-op.sh rm bge-m3")) == 1


def test_a_pull_that_fails_exits_1_without_a_digest_check(gpu: GpuWorld) -> None:
    gpu.set_tags([])
    gpu.ssh(status_csv(free_kb=_need_kb("bge-m3")), ops_rc=1)
    res = gpu.script("fetch-model.sh", BGE)
    assert res.rc == 1
    assert not _remote(gpu, "ollama-op.sh rm")


def test_dry_run_with_another_digest_prints_rm_and_exits_1(gpu: GpuWorld) -> None:
    gpu.ssh(status_csv(free_kb=_need_kb("bge-m3") + 10))
    gpu.set_tags(["bge-m3"], digests={"bge-m3": "9" * 64})
    res = gpu.script("fetch-model.sh", BGE, "--dry-run")
    assert res.rc == 1
    assert "DRY-RUN cluster rm bge-m3" in res.out
    assert not _remote(gpu, "ollama-op.sh")


def test_dry_run_prints_the_pull_and_runs_nothing_remote_but_the_read(gpu: GpuWorld) -> None:
    gpu.ssh(status_csv(free_kb=_need_kb("bge-m3") + 10))
    gpu.set_tags([])
    res = gpu.script("fetch-model.sh", BGE, "--dry-run")
    assert res.rc == 0, res.err
    assert "DRY-RUN cluster pull bge-m3" in res.out
    assert not _remote(gpu, "ollama-op.sh")


def test_dry_run_still_refuses_for_lack_of_space(gpu: GpuWorld) -> None:
    gpu.ssh(status_csv(free_kb=10))
    gpu.set_tags([])
    assert gpu.script("fetch-model.sh", JUDGE, "--dry-run").rc == 17


@pytest.mark.parametrize(
    "bad", ["ollama/nope:1b", "bge-m3", "ollama/bge-m3;reboot", "BAAI/bge-reranker-v2-m3"]
)
def test_ids_outside_the_ollama_catalogue_exit_64(gpu: GpuWorld, bad: str) -> None:
    assert gpu.script("fetch-model.sh", bad).rc == 64
    assert not gpu.stubs.calls("ssh")


def test_no_id_is_a_usage_error(gpu: GpuWorld) -> None:
    assert gpu.script("fetch-model.sh").rc == 64


def test_rm_without_maintenance_exits_3(gpu: GpuWorld) -> None:
    res = gpu.script("fetch-model.sh", "--rm", JUDGE)
    assert res.rc == 3
    assert "set MAINTENANCE for a model swap" in res.err
    assert not _remote(gpu, "ollama-op.sh")


def test_rm_with_maintenance_removes_a_non_generator_model(gpu: GpuWorld) -> None:
    (gpu.lock_dir / "MAINTENANCE").touch()
    res = gpu.script("fetch-model.sh", "--rm", JUDGE)
    assert res.rc == 0, res.err
    assert len(_remote(gpu, "ollama-op.sh rm gemma3:12b")) == 1
    assert (gpu.lock_dir / "MAINTENANCE").exists()


def test_rm_of_the_generator_exits_64_with_or_without_maintenance(gpu: GpuWorld) -> None:
    for with_maintenance in (False, True):
        if with_maintenance:
            (gpu.lock_dir / "MAINTENANCE").touch()
        res = gpu.script("fetch-model.sh", "--rm", GEN)
        assert res.rc == 64
        assert "generator" in res.err
    assert not _remote(gpu, "ollama-op.sh")


def test_the_generator_present_with_its_pin_needs_no_pull(gpu: GpuWorld) -> None:
    gpu.set_tags(["qwen3.8:27b-q8_0"])
    res = gpu.script("fetch-model.sh", GEN)
    assert res.rc == 0
    assert not _remote(gpu, "ollama-op.sh")


def test_the_reserve_is_two_gib() -> None:
    assert RESERVE_KB * 1024 == 2 * GIB

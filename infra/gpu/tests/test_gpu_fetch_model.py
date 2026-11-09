"""T3.1a CPU tests: ``fetch-model.sh`` (pull, digest check, the disk rule, ``--rm``; ADR-0019)."""

import pytest
import yaml
from gpu_testkit import GPU_DIR
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
    assert pulls[0].endswith("ollama-op.sh pull bge-m3 1157672605")  # the cluster re-checks size
    assert "/data/example/pruefstand-bin/ollama-op.sh" in pulls[0]
    assert not _remote(gpu, "ollama-op.sh rm")
    assert "digest matches" in res.out  # Ollama listed it as bge-m3:latest


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


def test_rm_removes_a_candidate_generator_but_never_the_standard_one(gpu: GpuWorld) -> None:
    """A non-standard entry with role generator (qwen3:4b) is a swap candidate."""
    (gpu.lock_dir / "MAINTENANCE").touch()
    res = gpu.script("fetch-model.sh", "--rm", "ollama/qwen3:4b")
    assert res.rc == 0, res.err
    assert len(_remote(gpu, "ollama-op.sh rm qwen3:4b")) == 1


def test_the_generator_present_with_its_pin_needs_no_pull(gpu: GpuWorld) -> None:
    gpu.set_tags(["qwen3.8:27b-q8_0"])
    res = gpu.script("fetch-model.sh", GEN)
    assert res.rc == 0
    assert not _remote(gpu, "ollama-op.sh")


def test_the_reserve_is_two_gib() -> None:
    assert RESERVE_KB * 1024 == 2 * GIB


def _broken_catalogue(gpu: GpuWorld, **changes: object) -> str:
    data = yaml.safe_load((GPU_DIR / "models.yaml").read_text(encoding="utf-8"))
    for entry in data["models"]:
        if entry["id"] == BGE:
            for key, value in changes.items():
                if value is None:
                    entry.pop(key, None)
                else:
                    entry[key] = value
    path = gpu.root / "broken-models.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return str(path)


@pytest.mark.parametrize(
    "changes",
    [
        {"disk_bytes": None}, {"disk_bytes": 0}, {"digest": None}, {"digest": "abc"},
        {"digest": "G" * 64},
    ],
)  # fmt: skip
def test_an_incomplete_catalogue_entry_is_refused_before_anything_runs(
    gpu: GpuWorld, changes: dict[str, object]
) -> None:
    gpu.set_tags([])
    gpu.ssh(status_csv(free_kb=10**9))
    res = gpu.script(
        "fetch-model.sh", BGE, PRUEFSTAND_GPU_CATALOGUE=_broken_catalogue(gpu, **changes)
    )
    assert res.rc == 1
    assert not gpu.stubs.calls("ssh")
    assert not gpu.stubs.calls("curl")


@pytest.mark.parametrize(
    "body",
    ["", "none", "{not json", '{"models": []}', '{"models": [{"name": "bge-m3:latest"}]}'],
)
def test_an_unreadable_digest_never_removes_the_model(gpu: GpuWorld, body: str) -> None:
    gpu.set_tags([])
    gpu.ssh(status_csv(free_kb=_need_kb("bge-m3")), pulled_raw=body)
    res = gpu.script("fetch-model.sh", BGE)
    assert res.rc == 1
    assert "could not read" in res.out + res.err
    assert not _remote(gpu, "ollama-op.sh rm")  # only a positive mismatch deletes
    assert len(_remote(gpu, "ollama-op.sh pull bge-m3")) == 1


def test_only_a_positive_digest_mismatch_removes_the_model(gpu: GpuWorld) -> None:
    gpu.set_tags([])
    gpu.ssh(status_csv(free_kb=_need_kb("bge-m3")), pulled={"bge-m3": "9" * 64})
    assert gpu.script("fetch-model.sh", BGE).rc == 1
    assert len(_remote(gpu, "ollama-op.sh rm bge-m3")) == 1

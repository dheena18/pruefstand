"""T3.1a CPU tests: ``ollama-op.sh`` (pull / rm / show; the disk rule, generator protection)."""

import pytest
from gpu_testkit import ClusterWorld

DF_HEAD = "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
DF_OK = DF_HEAD + "/dev/sdb1 500000000 480000000 14000000 97% /data"
DF_LOW = DF_OK.replace("14000000", "1500000")


def _ready(world: ClusterWorld, df: str = DF_OK) -> None:
    world.add_serve(4242)
    world.stub_server([4242])
    world.stubs.add("df", [("*", df, 0)])


@pytest.mark.parametrize(
    "args",
    [
        (),
        ("pull",),
        ("zap", "bge-m3"),
        ("pull", "x; reboot", "1"),
        ("pull", "-rf", "1"),
        ("rm", "a", "b"),
        ("pull", "bge-m3"),
        ("pull", "bge-m3", "abc"),
        ("pull", "bge-m3", "-5"),
        ("pull", "bge-m3", "1.5"),
        ("pull", "bge-m3", "1", "2"),
        ("pull", "../../x", "1"),
    ],
)
def test_bad_usage_exits_64_and_runs_nothing(world: ClusterWorld, args: tuple[str, ...]) -> None:
    _ready(world)
    assert world.script("ollama-op.sh", *args).rc == 64
    assert not world.stubs.calls("ollama")


def test_the_generator_is_never_removed(world: ClusterWorld) -> None:
    _ready(world)
    res = world.script("ollama-op.sh", "rm", "qwen3.8:27b-q8_0")
    assert res.rc == 64
    assert "generator" in res.err
    assert "ollama rm" not in world.stubs.log.read_text()


def test_rm_of_another_model_calls_the_server_binary(world: ClusterWorld) -> None:
    _ready(world)
    assert world.script("ollama-op.sh", "rm", "gemma3:12b").rc == 0
    assert "ollama rm gemma3:12b" in world.stubs.log.read_text()


def test_pull_with_enough_free_space_pulls(world: ClusterWorld) -> None:
    _ready(world)
    assert world.script("ollama-op.sh", "pull", "bge-m3", "1157672605").rc == 0
    assert "ollama pull bge-m3" in world.stubs.log.read_text()


FREE_KB = 14_000_000
RESERVE_KB = 2 * 1024 * 1024


def test_pull_needs_the_model_size_plus_the_reserve_not_just_the_reserve(
    world: ClusterWorld,
) -> None:
    _ready(world)
    exact = (FREE_KB - RESERVE_KB) * 1024  # bytes that leave exactly the reserve
    assert world.script("ollama-op.sh", "pull", "gemma3:12b", str(exact)).rc == 0
    world.stubs.log.write_text("")
    res = world.script("ollama-op.sh", "pull", "gemma3:12b", str(exact + 1))
    assert res.rc == 17
    assert "owner" in res.err
    assert "ollama pull" not in world.stubs.log.read_text()


@pytest.mark.parametrize(
    "df_out", ["", "garbage", "Filesystem 1 2 3 x% /\n/dev/x 1 2 notanumber 9% /"]
)
def test_an_unreadable_free_space_fails_closed_with_17(world: ClusterWorld, df_out: str) -> None:
    world.add_serve(4242)
    world.stub_server([4242])
    world.stubs.add("df", [("*", df_out, 0)])
    assert world.script("ollama-op.sh", "pull", "bge-m3", "1").rc == 17
    assert "ollama pull" not in world.stubs.log.read_text()


def test_the_free_space_is_measured_on_the_models_filesystem_only(world: ClusterWorld) -> None:
    world.add_serve(4242)
    world.stub_server([4242])
    world.stubs.add("df", [("*", "", 1)])  # df of the models dir fails: no fallback to /data
    assert world.script("ollama-op.sh", "pull", "bge-m3", "1").rc == 17
    calls = world.stubs.calls("df")
    assert calls
    assert all(str(world.models) in c for c in calls)
    assert not any(c.endswith(" /data") for c in calls)


def test_pull_without_the_reserve_free_stops_with_17_and_asks_the_owner(
    world: ClusterWorld,
) -> None:
    _ready(world, DF_LOW.replace("1500000", "1048576"))
    res = world.script("ollama-op.sh", "pull", "bge-m3", "1157672605")
    assert res.rc == 17
    assert "owner" in res.err
    assert "ollama pull" not in world.stubs.log.read_text()


def test_show_needs_no_free_space(world: ClusterWorld) -> None:
    _ready(world, DF_LOW.replace("1500000", "10"))
    assert world.script("ollama-op.sh", "show", "bge-m3").rc == 0
    assert "ollama show bge-m3" in world.stubs.log.read_text()


def test_without_a_running_server_there_is_no_binary(world: ClusterWorld) -> None:
    world.stub_server([])
    world.stubs.add("df", [("*", DF_OK, 0)])
    res = world.script("ollama-op.sh", "show", "bge-m3")
    assert res.rc == 1
    assert "ollama" in res.err

"""T3.1e CPU tests: ``log-tail.sh`` (read-only Ollama log tail, redacted on the cluster)."""

import getpass
import hashlib

import pytest
from gpu_testkit import ClusterWorld
from vm_testkit import Result

LOGIN = getpass.getuser()
AUTH = "Authorization: Bearer abcdef0123456789"
V6 = "ipv6=[fe80::1]:8080 addr=2001:db8::7"
IP = "10.20.30.40"
OTHER = "192.168.7.9"
TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
HEX64 = "2bb22714289826d7b9e0ba376c3ce47d08bce39abe598745857c44d88c09bdbf"


TS = "time=2026-11-03T10:00:0"
HOSTED = "ssh {login}@gpu-node7.example.net"
GIN = "[GIN] 2026/11/03 - 10:00:0"


def _sample(world: ClusterWorld) -> str:
    """A realistic server log: config, model load lines, runner start, requests, a leaky tail."""
    models, home = world.models, world.home
    blob = f"{models}/blobs/sha256-{HEX64}"
    cfg = f"OLLAMA_HOST:http://127.0.0.1:11434 OLLAMA_MODELS:{models} OLLAMA_NUM_PARALLEL:4"
    runner = f"/data/{LOGIN}/ollama/bin/ollama runner --model {blob}"
    uuid = "GPU-1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d"
    return "\n".join(
        [
            f'{TS}0.000+01:00 level=INFO source=routes.go:1 msg="server config" env="map[{cfg}]"',
            f'{TS}1.000+01:00 level=INFO source=images.go:45 msg="model {blob}"',
            f'{TS}2.000+01:00 level=INFO source=server.go:300 cmd="{runner} --ctx-size 32768 '
            '--parallel 4 --port 41233"',
            "llama_context: n_ctx_seq = 8192",
            "llama_kv_cache: CUDA0 KV buffer size =  1024.00 MiB",
            "load_tensors: offloaded 65/65 layers to GPU",
            f'{TS}3.000+01:00 level=INFO source=sched.go:480 msg="loaded" id={uuid} count=1',
            f'{GIN}4 | 200 | 1.5s | {IP} | POST "/api/chat"',
            f'{GIN}5 | 200 | 2ms | 127.0.0.1 | GET "/api/tags"',
            'msg="listening on 127.0.0.1:11434 (version 0.32.1)"',
            f'msg="peer {OTHER}:2222 {HOSTED.format(login=LOGIN)} home={home}/.ollama"',
            f'msg="get https://registry.ollama.ai/v2/x token={TOKEN} {AUTH}"',
            f'msg="cwd {home}/work user {LOGIN} on {world.root.name}" {V6}',
        ]
    )


def _tail(world: ClusterWorld, *args: object, text: str | None = None) -> Result:
    world.log.write_text(text if text is not None else _sample(world) + "\n", encoding="utf-8")
    world.add_serve(4242)
    world.stub_server([4242])
    return world.script("log-tail.sh", *args, HOSTNAME="gpu-node7")


def test_the_real_redaction_removes_every_identifying_value(world: ClusterWorld) -> None:
    res = _tail(world)
    assert res.rc == 0, res.err
    out = res.out
    for secret in (
        LOGIN, str(world.home), str(world.models), IP, OTHER, TOKEN, HEX64, "abcdef0123456789",
        "gpu-node7", "example.net", "41233", "2222", "fe80", "2001:db8", "1a2b3c4d", "/data/",
    ):  # fmt: skip
        assert secret not in out, secret
    assert "OLLAMA_HOST:http://127.0.0.1:11434" in out
    assert "listening on 127.0.0.1:11434" in out
    assert "<models-dir>/blobs/sha256-<digest>" in out
    assert "<home>/.ollama" in out
    assert "<cluster-user>@<host>" in out or "<user>@<host>" in out
    assert "<data-dir>/ollama/bin/ollama runner" in out or "<ollama-bin>" in out
    assert "--port <port>" in out
    assert "token=<redacted>" in out
    assert "Authorization: <redacted>" in out
    assert "GPU-<uuid>" in out


def test_the_values_the_lead_needs_survive(world: ClusterWorld) -> None:
    out = _tail(world).out
    for kept in (
        "n_ctx_seq = 8192", "CUDA0 KV buffer size =  1024.00 MiB", "offloaded 65/65 layers to GPU",
        "--parallel 4", "--ctx-size 32768", "OLLAMA_NUM_PARALLEL:4",
        "time=2026-11-03T10:00:03.000+01:00",
    ):  # fmt: skip
        assert kept in out, kept


def test_the_ollama_binary_of_the_serve_process_becomes_a_placeholder(world: ClusterWorld) -> None:
    exe = world.root / "ollama-bin"
    text = f"starting {exe} serve\nunrelated line\n"
    res = _tail(world, text=text)
    assert res.rc == 0, res.err
    assert "starting <ollama-bin> serve" in res.out
    assert str(exe) not in res.out


@pytest.mark.parametrize(
    ("args", "lines"), [((), 200), (("5",), 5), (("1000",), 1000), (("1",), 1)]
)
def test_the_line_count_defaults_to_200_and_is_honoured(
    world: ClusterWorld, args: tuple[str, ...], lines: int
) -> None:
    text = "".join(f"line {i}\n" for i in range(1, 1501))
    res = _tail(world, *args, text=text)
    assert res.rc == 0, res.err
    got = res.out.splitlines()
    assert len(got) == lines
    assert got[-1] == "line 1500"


@pytest.mark.parametrize(
    "arg", ["0", "1001", "99999", "-5", "abc", "1.5", "010", "5; reboot", "$(id)", ""]
)
def test_a_bad_count_exits_64_and_prints_nothing(world: ClusterWorld, arg: str) -> None:
    res = _tail(world, arg)
    assert res.rc == 64
    assert res.out == ""


def test_two_arguments_exit_64(world: ClusterWorld) -> None:
    res = _tail(world, "5", "6")
    assert res.rc == 64
    assert res.out == ""


def test_it_only_reads_nothing_is_written_or_called(world: ClusterWorld) -> None:
    before = world.log.read_bytes() if world.log.exists() else b""
    res = _tail(world)
    assert res.rc == 0
    assert world.log.read_text(encoding="utf-8").startswith("time=")
    assert before == b""
    assert not (world.bin_dir / "log-tail.sh.partial").exists()
    for tool in ("curl", "ollama", "nvidia-smi", "pkill", "kill", "rm", "mv", "tee"):
        assert not world.stubs.calls(tool)
    digest = hashlib.sha256(world.log.read_bytes()).hexdigest()
    _tail(world, text=world.log.read_text(encoding="utf-8"))
    assert hashlib.sha256(world.log.read_bytes()).hexdigest() == digest


def test_a_missing_log_exits_1_and_prints_nothing(world: ClusterWorld) -> None:
    world.add_serve(4242)
    res = world.script("log-tail.sh")
    assert res.rc == 1
    assert res.out == ""
    assert str(world.log) not in res.err


def test_a_failing_sed_prints_nothing_and_exits_nonzero(world: ClusterWorld) -> None:
    world.stubs.link("sed", world.root / "absent-sed")
    res = _tail(world)
    assert res.rc != 0
    assert res.out == ""


def test_a_redaction_that_changes_nothing_is_caught_by_the_leak_scan(world: ClusterWorld) -> None:
    (world.stubs.bin / "sed").unlink(missing_ok=True)
    (world.stubs.bin / "sed").write_text(
        '#!/bin/sh\nif [ "$1" = "-E" ]; then exec cat; fi\nexec /usr/bin/sed "$@"\n'
    )
    (world.stubs.bin / "sed").chmod(0o755)
    res = _tail(world)
    assert res.rc == 5
    assert res.out == ""
    assert LOGIN not in res.err
    assert str(world.home) not in res.err


def test_a_short_login_is_still_scrubbed_by_name(world: ClusterWorld) -> None:
    text = f"cwd /srv/{LOGIN}/x and {LOGIN} again\n"
    res = _tail(world, text=text)
    assert res.rc == 0, res.err
    assert LOGIN not in res.out
    assert "<cluster-user>" in res.out


def test_control_characters_and_long_lines_are_cut(world: ClusterWorld) -> None:
    res = _tail(world, text="\x1b[31mred\x1b[0m ok\n" + "x " * 3000 + "\n")
    assert res.rc == 0, res.err
    assert "\x1b" not in res.out
    assert max(len(line) for line in res.out.splitlines()) <= 2000


def test_the_new_script_is_part_of_the_deployed_set(world: ClusterWorld) -> None:
    sums = (world.bin_dir / "SHA256SUMS").read_text(encoding="utf-8")
    assert "  log-tail.sh" in sums

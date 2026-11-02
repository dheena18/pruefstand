"""Regression tests: probe.sh finds the Ollama binary from the serving process (T0.6 fix).

Everything runs against synthetic paths in a temp dir. The probe sees only a private PATH that
holds symlinks to the plain tools it needs, so a tool such as `ss` or `ollama` exists only where
a test puts it. `PROBE_PROC_ROOT` points the /proc scan at a fake proc tree.
"""

import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "feasibility" / "probe.sh"
TOOLS = [
    "awk",
    "sed",
    "grep",
    "tr",
    "head",
    "tail",
    "cut",
    "sort",
    "uniq",
    "wc",
    "cat",
    "date",
    "id",
    "readlink",
    "stat",
    "ps",
    "pgrep",
    "df",
    "du",
    "uname",
    "dirname",
    "basename",
    "curl",
]
GEN = "qwen3.8:27b-q8_0"

FAKE_OLLAMA = """#!/bin/sh
case "$1" in
  --version) echo "ollama version is VERSION" ;;
  list) printf 'NAME ID SIZE MODIFIED\\n%s abc 28 GB now\\n' "QWEN" ;;
  show)
    if [ "$2" = "--modelfile" ]; then echo "FROM /blobs/sha256-0123456789abcdef0123"; else
      printf '  Model\\n    architecture        qwen3\\n    parameters          27B\\n'; fi ;;
esac
""".replace("QWEN", GEN)


def _exe(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _fake_ollama(path: Path, version: str) -> Path:
    return _exe(path, FAKE_OLLAMA.replace("VERSION", version))


def _proc(root: Path, pid: int, cmdline: list[str], exe: Path) -> None:
    pdir = root / str(pid)
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "cmdline").write_bytes(b"\0".join(c.encode() for c in cmdline) + b"\0")
    (pdir / "exe").symlink_to(exe)


class Rig:
    """A private PATH, fake proc root and fake home for one probe run."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.bin = tmp / "pathbin"
        self.bin.mkdir()
        self.proc = tmp / "proc"
        self.proc.mkdir()
        self.home = tmp / "home" / "exuser"
        self.home.mkdir(parents=True)
        for tool in TOOLS:
            found = shutil.which(tool)
            if found:
                (self.bin / tool).symlink_to(found)

    def run(self, checks: str, **extra: str) -> str:
        env = {
            "PATH": str(self.bin),
            "HOME": str(self.home),
            "PROBE_PROC_ROOT": str(self.proc),
            "PROBE_CHECKS": checks,
            "GEN_MODEL": GEN,
            **extra,
        }
        proc = subprocess.run(  # noqa: S603  # fixed argv, no shell
            [shutil.which("bash") or "bash", str(SCRIPT)],
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        return proc.stdout


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


def _check(out: str, name: str) -> str:
    return next(line for line in out.splitlines() if line.startswith(f"CHECK {name} "))


def test_binary_found_by_scanning_proc_when_not_on_path(rig: Rig) -> None:
    binary = _fake_ollama(rig.home / "tools" / "bin" / "ollama", "1.2.3")
    _proc(rig.proc, 4242, ["x/ollama", "serve"], binary)
    out = rig.run("ollama")
    assert (
        _check(out, "ollama").rstrip() == "CHECK ollama PASS <ollama-bin>: ollama version is 1.2.3"
    )


def test_binary_follows_the_pid_that_listens_on_11434(rig: Rig) -> None:
    serving = _fake_ollama(rig.tmp / "opt/example/bin/ollama", "7.7.7")
    decoy = _fake_ollama(rig.tmp / "opt/other/bin/ollama", "0.0.1")
    _proc(rig.proc, 99, ["ollama", "serve"], decoy)
    _proc(rig.proc, 4242, ["ollama", "serve"], serving)
    _exe(
        rig.bin / "ss",
        "#!/bin/sh\necho 'LISTEN 0 4096 127.0.0.1:11434 0.0.0.0:* "
        'users:(("ollama",pid=4242,fd=3))\'\n',
    )
    assert "7.7.7" in _check(rig.run("ollama"), "ollama")


def test_proc_scan_ignores_processes_that_are_not_ollama_serve(rig: Rig) -> None:
    binary = _fake_ollama(rig.tmp / "opt/example/bin/ollama", "1.0.0")
    _proc(rig.proc, 50, ["ollama", "run", "x"], binary)
    assert _check(rig.run("ollama"), "ollama").startswith("CHECK ollama FAIL")


def test_binary_falls_back_to_command_v(rig: Rig) -> None:
    binary = _fake_ollama(rig.tmp / "elsewhere" / "ollama", "3.3.3")
    (rig.bin / "ollama").symlink_to(binary)
    assert "3.3.3" in _check(rig.run("ollama"), "ollama")


def test_binary_missing_everywhere_fails(rig: Rig) -> None:
    out = rig.run("ollama ollama-list ollama-provenance")
    assert _check(out, "ollama").startswith("CHECK ollama FAIL")
    assert "ollama binary not found" in _check(out, "ollama")


def test_list_and_provenance_use_the_found_binary(rig: Rig) -> None:
    binary = _fake_ollama(rig.tmp / "opt/example/bin/ollama", "1.2.3")
    _proc(rig.proc, 4242, ["ollama", "serve"], binary)
    _exe(rig.bin / "curl", "#!/bin/sh\nprintf 200\n")
    out = rig.run("ollama-list ollama-provenance")
    assert _check(out, "ollama-list").startswith("CHECK ollama-list PASS")
    assert "arch=qwen3" in _check(out, "ollama-list")
    assert _check(out, "ollama-provenance").startswith("CHECK ollama-provenance PASS")
    assert "binary not found" not in out


def test_output_never_leaks_the_binary_path_or_the_home_directory(rig: Rig) -> None:
    binary = _fake_ollama(rig.home / "tools" / "bin" / "ollama", "1.2.3")
    _proc(rig.proc, 4242, ["ollama", "serve"], binary)
    _exe(rig.bin / "curl", "#!/bin/sh\nprintf 200\n")
    models = rig.home / "models"
    models.mkdir()
    out = rig.run("ollama ollama-list ollama-provenance models-space", MODELS_DIR=str(models))
    assert "<ollama-bin>" in out
    assert str(binary) not in out
    assert str(rig.home) not in out
    assert "exuser" not in out
    assert "<models-dir>" in out

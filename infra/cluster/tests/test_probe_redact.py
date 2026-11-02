"""Hardening tests for probe.sh: confidentiality filter and safe binary discovery (T0.6 fix).

All names are synthetic. A fake `id` reports the login `LoginX` (or what a test asks for), so no
real account name appears here. The probe sees only a private PATH of symlinks plus what a test
adds.
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "feasibility" / "probe.sh"
GEN = "qwen3.8:27b-q8_0"
TOOLS = [
    "awk", "sed", "grep", "tr", "head", "tail", "cut", "sort", "uniq", "wc", "cat", "date",
    "readlink", "stat", "ps", "df", "du", "uname", "dirname", "basename", "curl", "sleep",
]  # fmt: skip

FAKE_OLLAMA = """#!/bin/sh
case "$1" in
  --version)
    [ -z "$FAKE_STDERR" ] || echo "$FAKE_STDERR" >&2
    echo "ollama version is 1.2.3 ${FAKE_VERSION_EXTRA:-}" ;;
  list) printf 'NAME ID SIZE MODIFIED\\n%s abc 28 GB now\\n' "GENMODEL" ;;
  show)
    if [ "$2" = "--modelfile" ]; then
      echo "${FAKE_FROM:-FROM /blobs/sha256-0123456789abcdef0123}"; else
      printf '  Model\\n    architecture        qwen3\\n    parameters          27B\\n'; fi ;;
esac
""".replace("GENMODEL", GEN)


def exe(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


class Rig:
    """A private PATH, fake proc root, fake home and fake login for one probe run."""

    def __init__(self, tmp: Path, login: str = "LoginX") -> None:
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
        real_id = shutil.which("id") or "id"
        exe(
            self.bin / "id",
            f'#!/bin/sh\n[ "$1" = -un ] && echo {login} && exit 0\nexec {real_id} "$@"\n',
        )

    def ollama(self, path: Path) -> Path:
        return exe(path, FAKE_OLLAMA)

    def serve(self, pid: int, binary: Path, cmdline: list[str] | None = None) -> Path:
        pdir = self.proc / str(pid)
        pdir.mkdir(parents=True, exist_ok=True)
        argv = cmdline or ["ollama", "serve"]
        (pdir / "cmdline").write_bytes(b"\0".join(c.encode() for c in argv) + b"\0")
        (pdir / "exe").symlink_to(binary)
        return pdir

    def run(self, checks: str, extra_path: list[Path] | None = None, **extra: str) -> str:
        path = os.pathsep.join(str(p) for p in [*(extra_path or []), self.bin])
        env = {"PATH": path, "HOME": str(self.home), "PROBE_PROC_ROOT": str(self.proc),
               "PROBE_CHECKS": checks, "GEN_MODEL": GEN, **extra}  # fmt: skip
        proc = subprocess.run(  # noqa: S603  # fixed argv, no shell
            [shutil.which("bash") or "bash", str(SCRIPT)],
            capture_output=True, text=True, check=False, env=env, timeout=60,
        )  # fmt: skip
        assert proc.returncode == 0, proc.stderr
        return proc.stdout


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


def line(out: str, name: str) -> str:
    return next(x for x in out.splitlines() if x.startswith(f"CHECK {name} "))


def test_install_prefix_outside_home_is_scrubbed(rig: Rig) -> None:
    prefix = rig.tmp / "opt" / "LoginX" / "ollama"
    rig.serve(4242, rig.ollama(prefix / "bin" / "ollama"))
    out = rig.run("ollama", FAKE_VERSION_EXTRA=f"libs {prefix}/lib/ollama/libggml.so")
    assert "LoginX" not in out
    assert "<ollama-prefix>/lib/ollama/libggml.so" in out


def test_symlinked_home_is_scrubbed_by_its_resolved_path(rig: Rig) -> None:
    real = rig.tmp / "real" / "h"
    real.mkdir(parents=True)
    link = rig.tmp / "linkhome"
    link.symlink_to(real)
    rig.home = link
    rig.serve(4242, rig.ollama(rig.tmp / "opt" / "x" / "ollama"))
    out = rig.run("ollama", FAKE_VERSION_EXTRA=f"cfg {real}/.ollama/cfg")
    assert str(real) not in out
    assert "<home>/.ollama/cfg" in out


def test_passwd_home_is_scrubbed(rig: Rig) -> None:
    pw = rig.tmp / "srv" / "pwhome"
    exe(rig.bin / "getent", f"#!/bin/sh\necho 'LoginX:x:1:1::{pw}:/bin/sh'\n")
    rig.serve(4242, rig.ollama(rig.tmp / "opt" / "x" / "ollama"))
    out = rig.run("ollama", FAKE_VERSION_EXTRA=f"data {pw}/blobs")
    assert str(pw) not in out
    assert "<home>/blobs" in out


def test_uppercase_login_is_scrubbed_whatever_its_case(rig: Rig) -> None:
    models = rig.tmp / "data" / "loginx" / "Models"
    out = rig.run("models-space", MODELS_DIR=str(models))
    assert "loginx" not in out.lower().replace("<cluster-user>", "")
    assert "/<cluster-user>/Models" in out


def test_short_login_does_not_mangle_other_words(tmp_path: Path) -> None:
    rig = Rig(tmp_path, login="ab")
    rig.home = tmp_path / "home" / "ab"
    rig.home.mkdir(parents=True)
    models = tmp_path / "home" / "abc" / "label" / "ab" / "m"
    out = rig.run("models-space", MODELS_DIR=str(models))
    assert "home/abc/label/<cluster-user>/m" in out
    assert "<home>c" not in out


def test_header_and_store_and_vllm_do_not_leak(rig: Rig) -> None:
    models = rig.tmp / "opt" / "LoginX" / "models"
    rig.serve(4242, rig.ollama(rig.tmp / "opt" / "x" / "ollama"))
    (rig.proc / "4242" / "environ").write_bytes(f"OLLAMA_MODELS={models}\0".encode())
    vbin = rig.tmp / "opt" / "LoginX" / "vbin"
    exe(vbin / "vllm", "#!/bin/sh\n")
    out = rig.run("ollama-store vllm", extra_path=[vbin], MODELS_DIR=str(models))
    assert "LoginX" not in out
    assert "vllm present" in out


def test_modelfile_from_line_does_not_leak(rig: Rig) -> None:
    rig.serve(4242, rig.ollama(rig.tmp / "opt" / "x" / "ollama"))
    exe(rig.bin / "curl", "#!/bin/sh\nprintf 200\n")
    out = rig.run("ollama-provenance", FAKE_FROM=f"FROM {rig.tmp}/opt/LoginX/m/foo.gguf")
    assert "LoginX" not in out
    assert "FROM" in line(out, "ollama-provenance")


def test_a_line_that_still_holds_the_login_is_suppressed(rig: Rig) -> None:
    rig.serve(4242, rig.ollama(rig.tmp / "opt" / "x" / "ollama"))
    out = rig.run("ollama", FAKE_VERSION_EXTRA="built by loginx today")
    assert "CHECK redact FAIL leak suppressed" in out
    assert "loginx" not in out.lower()


def test_listener_that_is_not_ollama_is_never_executed(rig: Rig) -> None:
    marker = rig.tmp / "ran"
    ssh = exe(rig.tmp / "opt" / "bin" / "ssh", f"#!/bin/sh\ntouch {marker}\necho OpenSSH\n")
    rig.serve(777, ssh)
    exe(
        rig.bin / "ss",
        "#!/bin/sh\necho 'LISTEN 0 1 127.0.0.1:11434 0.0.0.0:* users:((\"ssh\",pid=777,fd=3))'\n",
    )
    out = rig.run("ollama ollama-list")
    assert not marker.exists()
    assert line(out, "ollama").startswith("CHECK ollama FAIL")
    assert line(out, "ollama-list").startswith("CHECK ollama-list FAIL")


def test_exe_that_is_not_a_regular_file_is_rejected(rig: Rig) -> None:
    folder = rig.tmp / "opt" / "ollama"
    folder.mkdir(parents=True)
    rig.serve(4242, folder)
    assert line(rig.run("ollama"), "ollama").startswith("CHECK ollama FAIL")


@pytest.mark.skipif(os.geteuid() == 0, reason="root owns everything")
def test_pid_directory_owned_by_someone_else_is_rejected(rig: Rig) -> None:
    (rig.proc / "1").symlink_to("/proc/1")
    assert line(rig.run("ollama"), "ollama").startswith("CHECK ollama FAIL")


@pytest.mark.parametrize(
    "argv", [["vim", "ollama", "serve-notes"], ["vim", "ollama serve"], ["ollama", "run", "x"]]
)
def test_proc_scan_needs_ollama_serve_as_argv(rig: Rig, argv: list[str]) -> None:
    rig.serve(50, rig.ollama(rig.tmp / "opt" / "x" / "ollama"), argv)
    assert line(rig.run("ollama"), "ollama").startswith("CHECK ollama FAIL")


LONGER = [
    "/srv/exuser-data/models",
    "/data/exuser_models",
    "/srv/exuser.log",
    "/data/exuserdata",
    "/home/exuser.bak/x",
    "%2Fhome%2Fexuser%2Fx",
]


@pytest.mark.parametrize("models", LONGER, ids=[f"case{i}" for i in range(len(LONGER))])
def test_login_inside_a_longer_name_is_suppressed(tmp_path: Path, models: str) -> None:
    rig = Rig(tmp_path, login="exuser")
    out = rig.run("models-space", MODELS_DIR=models)
    assert "exuser" not in out.lower()
    assert "CHECK redact FAIL leak suppressed" in out


def test_stderr_of_the_binary_is_filtered_too(tmp_path: Path) -> None:
    rig = Rig(tmp_path, login="exuser")
    rig.serve(4242, rig.ollama(tmp_path / "opt" / "x" / "ollama"))
    out = rig.run("ollama", FAKE_STDERR="wrote /srv/exuser-cfg/x")
    assert "exuser" not in out
    assert "CHECK redact FAIL leak suppressed" in out


def test_published_model_directory_stays_visible(tmp_path: Path) -> None:
    rig = Rig(tmp_path, login="exuser")
    out = rig.run("models-space", MODELS_DIR="/data/exuser/Models")
    assert "/data/<cluster-user>/Models" in out
    assert "leak suppressed" not in out
